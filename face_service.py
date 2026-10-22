import multiprocessing as mp
import os
import queue
import threading
import time
import uuid
from collections import OrderedDict, deque
import cv2
import numpy as np

try:
    import face_recognition
except ImportError:  # permite subir o site sem a lib (o totem fica indisponível)
    face_recognition = None

from database import db, Aluno, registrar_presenca_totem, agora_local, hoje_local

# de onde vêm as imagens: "tablet" (câmera do navegador do tablet) ou "camera" (webcam ligada no servidor)
FONTE = os.getenv("TOTEM_FONTE", "tablet").strip().lower()
# só registra depois de ver o rosto se mexer sozinho (foto impressa tem olhos e boca parados)
PROVA_DE_VIDA = os.getenv("PROVA_DE_VIDA", "1") != "0"

TOLERANCIA = 0.50        # menor = mais rígido
CONFIRMACOES = 2         # encodings seguidos com o mesmo aluno antes de registrar
COOLDOWN = 8.0           # segundos antes de reconhecer o MESMO aluno de novo
PAUSA_APOS_EVENTO = 3.0  # segundos "descansando" depois de qualquer registro
INTERVALO = 0.05         # segundos entre duas voltas do envio de frames ao processo de reconhecimento
QUADRO_VELHO = 2.0       # frame mais velho que isso não serve (tablet parou de mandar)

# quando calcular o encoding (a parte cara)
ROSTO_MINIMO = 40        # px de altura no frame reduzido; menor que isso está longe demais
TENTAR_DE_NOVO = 0.5     # rosto desconhecido: no máximo 2 encodings por segundo
REVERIFICAR = 3.0        # rosto já reconhecido: confere de novo a cada 3 s
MESMO_ROSTO_IOU = 0.4    # sobreposição mínima entre caixas p/ considerar o mesmo rosto

# prova de vida passiva: rosto vivo mexe sozinho (olhos e boca variam entre frames); foto impressa não.
# vivo = a abertura dos olhos ou da boca variou mais que VARIACAO_VIVO (relativo) em até JANELA_VIVO frames
OLHO_ABERTO_MIN = 0.20
VARIACAO_VIVO = float(os.getenv("VARIACAO_VIVO", "0.12"))
JANELA_VIVO = 8
FRAMES_MIN_VIVO = 3

DLIB_LOCK = threading.Lock()   # cadastro por foto (admin) roda no processo do site


def encoding_de_arquivo(caminho):
    """Encoding facial de uma foto em disco (None se não houver exatamente 1 rosto)."""
    if face_recognition is None:
        return None
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(caminho)).convert("RGB")
    img.thumbnail((900, 900))            # foto de celular enorme = detecção lenta
    rgb = np.array(img)
    with DLIB_LOCK:
        locs = face_recognition.face_locations(rgb, model="hog")
        if len(locs) != 1:
            return None
        return face_recognition.face_encodings(rgb, locs)[0].astype(np.float64)


# =====================================================================
# Processo de reconhecimento (roda separado do site, com o próprio GIL)
# =====================================================================
def _iou(a, b):
    """Quanto duas caixas (top, right, bottom, left) se sobrepõem, de 0 a 1."""
    t, r = max(a[0], b[0]), min(a[1], b[1])
    bo, l = min(a[2], b[2]), max(a[3], b[3])
    inter = max(0, r - l) * max(0, bo - t)
    area = lambda c: (c[2] - c[0]) * (c[1] - c[3])
    return inter / float(area(a) + area(b) - inter or 1)


def abertura_olhos(pontos):
    """EAR (eye aspect ratio) de um olho com 6 pontos: ~0,3 aberto, ~0,1 fechado."""
    p = np.asarray(pontos, dtype=float)
    vertical = np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])
    horizontal = 2.0 * np.linalg.norm(p[0] - p[3])
    return vertical / horizontal if horizontal else 0.0


def abertura_boca(top_lip, bottom_lip):
    """Distância entre os lábios internos dividida pela largura da boca."""
    t, b = np.asarray(top_lip, dtype=float), np.asarray(bottom_lip, dtype=float)
    largura = np.linalg.norm(t[0] - t[6])
    return np.linalg.norm(t[9] - b[9]) / largura if largura else 0.0


def _variou(valores, piso):
    hi = max(valores)
    return hi >= piso and (hi - min(valores)) / hi >= VARIACAO_VIVO


def atualizar_vivo(trilha, marcos):
    """Guarda olhos/boca dos últimos frames e marca trilha['vivo'] quando o rosto se mexe por conta própria."""
    ear = (abertura_olhos(marcos["left_eye"]) + abertura_olhos(marcos["right_eye"])) / 2
    boca = abertura_boca(marcos["top_lip"], marcos["bottom_lip"])
    trilha["olhos"].append(ear)
    trilha["boca"].append(boca)
    if len(trilha["olhos"]) < FRAMES_MIN_VIVO:
        return
    if _variou(trilha["olhos"], OLHO_ABERTO_MIN) or _variou(trilha["boca"], 0.05):
        trilha["vivo"] = True


def _nova_trilha():
    return {"aluno_id": None, "seq": 0, "confirmado": False, "t_enc": 0.0, "vivo": False,
            "registrado": False, "olhos": deque(maxlen=JANELA_VIVO), "boca": deque(maxlen=JANELA_VIVO)}


def processo_reconhecimento(entrada, saida, prova_de_vida=True):
    """Recebe frames reduzidos (RGB) de um ou mais totens e devolve onde está o rosto e de quem é.

    Detecta rosto em todo frame (barato), mas só calcula o encoding (caro) quando aparece um rosto
    novo, faltam confirmações, ou chegou a hora de reverificar. Cada totem (chave) tem a sua trilha.
    Mensagens: ("frame", chave, fid, rgb) | ("rostos", ids, encs) | ("cadastro", pedido, [rgb])
               ("esquecer", chave) | ("fim",)
    Resposta:  ("deteccao", chave, fid, caixa, aluno_id, estado, novo_evento)
    estado: sem_rosto | longe | verificando | desconhecido | pisque | ok
    """
    import face_recognition as fr

    ids, encs = [], np.empty((0, 128))
    trilhas = {}

    def identificar(enc):
        if not len(ids):
            return None
        dist = np.linalg.norm(encs - enc, axis=1)
        i = int(np.argmin(dist))
        return ids[i] if dist[i] <= TOLERANCIA else None

    while True:
        msg = entrada.get()
        tipo = msg[0]
        try:
            if tipo == "fim":
                return
            if tipo == "rostos":
                ids, encs = msg[1], msg[2]
                trilhas.clear()
                continue
            if tipo == "esquecer":
                trilhas.pop(msg[1], None)
                continue
            if tipo == "cadastro":
                _, pedido, frames = msg
                achados = []
                for rgb in frames:
                    locs = fr.face_locations(rgb, model="hog")
                    if len(locs) == 1:
                        achados.append(fr.face_encodings(rgb, locs)[0])
                media = np.mean(achados, axis=0).astype(np.float64) if achados else None
                saida.put(("cadastro", pedido, media))
                continue

            _, chave, fid, rgb = msg
            locs = fr.face_locations(rgb, model="hog")
            if not locs:
                trilhas.pop(chave, None)
                saida.put(("deteccao", chave, fid, None, None, "sem_rosto", False))
                continue

            caixa = max(locs, key=lambda c: (c[2] - c[0]) * (c[1] - c[3]))
            agora = time.time()
            trilha = trilhas.get(chave)
            if trilha is None or _iou(caixa, trilha["caixa"]) < MESMO_ROSTO_IOU:
                trilha = trilhas[chave] = _nova_trilha()
            trilha["caixa"] = caixa

            perto = (caixa[2] - caixa[0]) >= ROSTO_MINIMO
            if not perto:
                saida.put(("deteccao", chave, fid, caixa, None, "longe", False))
                continue

            # prova de vida passiva: mede olhos e boca em todo frame até ver o rosto se mexer
            if prova_de_vida and not trilha["vivo"]:
                marcos = fr.face_landmarks(rgb, [caixa])
                if marcos and "left_eye" in marcos[0] and "top_lip" in marcos[0]:
                    atualizar_vivo(trilha, marcos[0])

            if trilha["confirmado"]:
                precisa = agora - trilha["t_enc"] >= REVERIFICAR
            elif trilha["seq"] > 0:
                precisa = True                                  # falta confirmar
            else:
                precisa = agora - trilha["t_enc"] >= TENTAR_DE_NOVO

            if precisa:
                aluno_id = identificar(fr.face_encodings(rgb, [caixa])[0])
                trilha["t_enc"] = agora
                if trilha["confirmado"]:
                    if aluno_id != trilha["aluno_id"]:          # trocou a pessoa na frente da câmera
                        trilha.update(_nova_trilha(), caixa=caixa, t_enc=agora,
                                      aluno_id=aluno_id, seq=1 if aluno_id else 0)
                elif aluno_id is None:
                    trilha.update(aluno_id=None, seq=0)
                elif aluno_id == trilha["aluno_id"]:
                    trilha["seq"] += 1
                else:
                    trilha.update(aluno_id=aluno_id, seq=1)
                if trilha["aluno_id"] and trilha["seq"] >= CONFIRMACOES:
                    trilha["confirmado"] = True

            novo_evento = False
            if trilha["confirmado"] and not trilha["registrado"]:
                if trilha["vivo"] or not prova_de_vida:
                    trilha["registrado"] = novo_evento = True
                    estado = "ok"
                else:
                    estado = "pisque"
            elif trilha["registrado"]:
                estado = "ok"
            elif trilha["t_enc"] and trilha["aluno_id"] is None:
                estado = "desconhecido"
            else:
                estado = "verificando"

            saida.put(("deteccao", chave, fid, caixa, trilha["aluno_id"], estado, novo_evento))
        except Exception as e:                    # uma falha não pode matar o processo
            print(f"[reconhecimento] erro: {e}")
            if tipo == "cadastro":
                saida.put(("cadastro", msg[1], None))


# =====================================================================
# Totem (processo do site): frames, presença e foto
# =====================================================================
class Fluxo:
    """Imagens e resultados de UM totem (a webcam do servidor ou um tablet)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None            # último frame cru (BGR)
        self.frame_id = 0
        self.recebido_em = 0.0
        self.enviado = -1            # último frame mandado ao processo de reconhecimento
        self.enviados = OrderedDict()   # fid -> frame cheio (p/ recortar a foto)
        self.caixas = []             # [(top, right, bottom, left, cor)] no tamanho do frame
        self.estado = "sem_rosto"
        self.aluno_id = None
        self.eventos = deque(maxlen=20)
        self.livre_em = 0.0          # não reconhece antes desse instante
        self.pausado = False         # cadastro de rosto em andamento

    def guardar(self, frame):
        with self.lock:
            self.frame = frame
            self.frame_id += 1
            self.recebido_em = time.time()

    def atual(self):
        with self.lock:
            return (None, 0) if self.frame is None else (self.frame.copy(), self.frame_id)


class Totem:
    def __init__(self, app, camera=0, fonte=FONTE):
        self.app, self.camera, self.fonte = app, camera, fonte
        self.escala = 0.75 if fonte == "tablet" else 0.5   # tablet manda 640px; reduz menos para ver os olhos
        self.cap = None
        self.rodando = False
        self.iniciando = False
        self.erro = None
        self._start_lock = threading.Lock()
        self._ultima_tentativa = 0.0
        self.fluxos = {}
        self._fluxos_lock = threading.Lock()
        self.ids, self.encs = [], np.empty((0, 128))
        self.ultimo_evento = {}      # aluno_id -> timestamp

        self._proc = None
        self._entrada = self._saida = None
        self._cadastros = {}         # pedido -> [Event, resultado]
        self._ultimo_reinicio = 0.0

    def fluxo(self, chave):
        with self._fluxos_lock:
            if chave not in self.fluxos:
                self.fluxos[chave] = Fluxo()
            return self.fluxos[chave]

    # ---------- ciclo de vida ----------
    def iniciar(self):
        """Não bloqueia: sobe o reconhecimento (e a webcam, no modo câmera) em segundo plano."""
        with self._start_lock:
            if self.rodando or self.iniciando:
                return
            if time.time() - self._ultima_tentativa < 5:   # não martela uma câmera com erro
                return
            if face_recognition is None:
                self.erro = "Biblioteca face_recognition não instalada."
                return
            self._ultima_tentativa = time.time()
            self.iniciando = True
        threading.Thread(target=self._abrir_e_rodar, daemon=True).start()

    def _abrir_e_rodar(self):
        try:
            if self.fonte == "camera":
                # No Windows o backend padrão (MSMF) demora e engasga; DSHOW é bem mais leve.
                cap = cv2.VideoCapture(self.camera, cv2.CAP_DSHOW) if os.name == "nt" \
                    else cv2.VideoCapture(self.camera)
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)     # sem fila de frames velhos = sem atraso
                if not cap.isOpened():
                    self.erro = "Não foi possível abrir a câmera (tente TOTEM_CAMERA=1)."
                    return
                self.cap = cap
            self.erro = None
            self._iniciar_processo()
            self.rodando = True
            if self.fonte == "camera":
                threading.Thread(target=self._capturar, daemon=True).start()
            threading.Thread(target=self._alimentar, daemon=True).start()
            threading.Thread(target=self._ler_resultados, daemon=True).start()
        except Exception as e:                      # nunca derruba o servidor
            self.erro = f"Erro ao iniciar o reconhecimento: {e}"
        finally:
            self.iniciando = False

    def _iniciar_processo(self):
        ctx = mp.get_context("spawn")
        self._entrada = ctx.Queue(maxsize=2)   # fila curta: frame velho é descartado, não acumula atraso
        self._saida = ctx.Queue()
        self._proc = ctx.Process(target=processo_reconhecimento, args=(self._entrada, self._saida, PROVA_DE_VIDA),
                                 name="reconhecimento-facial", daemon=True)
        self._proc.start()
        self.recarregar()

    def recarregar(self):
        """Carrega os rostos do banco e manda para o processo de reconhecimento."""
        with self.app.app_context():
            alunos = Aluno.query.filter(Aluno.face_encoding.isnot(None)).all()
            ids = [a.id for a in alunos]
            encs = [np.frombuffer(a.face_encoding, dtype=np.float64) for a in alunos]
        self.ids = ids
        self.encs = np.array(encs) if encs else np.empty((0, 128))
        if self._proc is not None and self._proc.is_alive():
            self._entrada.put(("rostos", self.ids, self.encs))

    # ---------- entrada de imagens ----------
    def _capturar(self):
        """Modo câmera: lê a webcam do servidor sem parar."""
        fluxo, falhas = self.fluxo("camera"), 0
        while self.rodando:
            ok, frame = self.cap.read()
            if not ok:
                falhas += 1
                if falhas > 100:
                    self.erro, self.rodando = "A câmera parou de responder.", False
                    self.cap.release()
                    return
                time.sleep(0.05)
                continue
            falhas = 0
            fluxo.guardar(frame)

    def receber_frame(self, chave, jpeg):
        """Modo tablet: guarda a foto que o navegador mandou e devolve o último resultado desse totem."""
        self.iniciar()
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("imagem inválida")
        if max(frame.shape[:2]) > 960:          # tablet que ignorou o tamanho pedido
            f = 960 / max(frame.shape[:2])
            frame = cv2.resize(frame, (0, 0), fx=f, fy=f)
        fluxo = self.fluxo(chave)
        fluxo.guardar(frame)
        caixa = fluxo.caixas[0][:4] if fluxo.caixas else None
        return {"caixa": caixa, "estado": fluxo.estado, "largura": frame.shape[1], "altura": frame.shape[0],
                "pronto": self.rodando, "erro": self.erro}

    def _alimentar(self):
        """Manda o frame mais novo (reduzido) de cada totem para o processo de reconhecimento."""
        while self.rodando:
            time.sleep(INTERVALO)
            if not self._proc.is_alive():
                # espera entre tentativas: se o processo não consegue subir, não fica abrindo sem parar
                if time.time() - self._ultimo_reinicio > 10:
                    print("[totem] processo de reconhecimento caiu; reiniciando")
                    self.erro = "Reconhecimento reiniciando..."
                    self._ultimo_reinicio = time.time()
                    self._iniciar_processo()
                continue
            if self.erro == "Reconhecimento reiniciando...":
                self.erro = None
            agora = time.time()
            for chave, fluxo in list(self.fluxos.items()):
                if fluxo.pausado or agora < fluxo.livre_em or agora - fluxo.recebido_em > QUADRO_VELHO:
                    continue
                frame, fid = fluxo.atual()
                if frame is None or fid == fluxo.enviado:
                    continue
                rgb = cv2.cvtColor(cv2.resize(frame, (0, 0), fx=self.escala, fy=self.escala), cv2.COLOR_BGR2RGB)
                try:
                    self._entrada.put_nowait(("frame", chave, fid, rgb))
                except queue.Full:                  # processo ocupado: tenta de novo na próxima volta
                    break
                fluxo.enviado = fid
                fluxo.enviados[fid] = frame
                while len(fluxo.enviados) > 5:
                    fluxo.enviados.popitem(last=False)

    def _ler_resultados(self):
        while self.rodando:
            try:
                msg = self._saida.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if msg[0] == "cadastro":
                    _, pedido, enc = msg
                    if pedido in self._cadastros:
                        self._cadastros[pedido][1] = enc
                        self._cadastros[pedido][0].set()
                    continue

                _, chave, fid, caixa, aluno_id, estado, novo_evento = msg
                fluxo = self.fluxo(chave)
                fluxo.estado, fluxo.aluno_id = estado, aluno_id
                if caixa is None:
                    fluxo.caixas = []
                    continue
                t, r, b, l = [int(v / self.escala) for v in caixa]
                fluxo.caixas = [(t, r, b, l, (0, 200, 0) if aluno_id else (0, 0, 255))]
                if novo_evento and time.time() - self.ultimo_evento.get(aluno_id, 0) > COOLDOWN:
                    self.ultimo_evento[aluno_id] = time.time()
                    fluxo.livre_em = time.time() + PAUSA_APOS_EVENTO
                    self._registrar(fluxo, aluno_id, fluxo.enviados.get(fid), (t, r, b, l))
            except Exception as e:                  # uma falha não pode matar a thread
                print(f"[totem] erro ao tratar reconhecimento: {e}")

    def _registrar(self, fluxo, aluno_id, frame=None, caixa=None):
        with self.app.app_context():
            aluno = db.session.get(Aluno, aluno_id)
            if not aluno:
                return
            status, ja = registrar_presenca_totem(aluno)
            if frame is not None:
                self._atualizar_foto(aluno, frame, caixa)
            agora = agora_local()
            fluxo.eventos.append({
                "nome": aluno.nome,
                "matricula": aluno.matricula,
                "foto": aluno.foto,
                "status": status,
                "ja_registrado": ja,
                "data": hoje_local().strftime("%d/%m/%Y"),
                "hora": agora.strftime("%H:%M:%S"),
            })
            print(f"[totem] {aluno.nome} -> {status}{' (já registrado hoje)' if ja else ''}")

    def _atualizar_foto(self, aluno, frame, caixa):
        """Troca a foto do aluno pelo rosto que a câmera acabou de ver (só a imagem de exibição)."""
        try:
            t, r, b, l = caixa
            altura, largura = frame.shape[:2]
            margem = int(max(b - t, r - l) * 0.45)
            recorte = frame[max(0, t - margem):min(altura, b + margem), max(0, l - margem):min(largura, r + margem)]
            if recorte.size == 0:
                return
            pasta = os.path.join(self.app.static_folder, "uploads")
            os.makedirs(pasta, exist_ok=True)
            nome = f"{uuid.uuid4().hex}.jpg"
            if not cv2.imwrite(os.path.join(pasta, nome), recorte, [cv2.IMWRITE_JPEG_QUALITY, 90]):
                return
            antiga, aluno.foto = aluno.foto, f"/static/uploads/{nome}"
            db.session.commit()
            if antiga and antiga.startswith("/static/uploads/"):
                caminho = os.path.join(pasta, os.path.basename(antiga))
                if os.path.isfile(caminho):
                    os.remove(caminho)
        except Exception as e:  # a presença já foi salva; a foto é só um extra
            db.session.rollback()
            print(f"[totem] não consegui atualizar a foto: {e}")

    # ---------- API usada pelas rotas ----------
    def proximo_evento(self, chave):
        try:
            return self.fluxo(chave).eventos.popleft()
        except IndexError:
            return None

    def stream(self):
        """Modo câmera: gerador MJPEG para <img src='/video_feed'>. Só codifica quando há frame novo."""
        fluxo, ultimo = self.fluxo("camera"), -1
        while True:
            frame, fid = fluxo.atual()
            if frame is None:
                img = np.zeros((480, 640, 3), np.uint8)
                msg = self.erro or "Iniciando camera..."
                cv2.putText(img, msg[:60].encode("ascii", "ignore").decode(), (20, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                time.sleep(0.5)
            elif fid == ultimo:
                time.sleep(0.01)
                continue
            else:
                ultimo = fid
                w = frame.shape[1]
                img = cv2.flip(frame, 1)    # espelho só na exibição; o reconhecimento usa o frame cru
                for (t, r, b, l, cor) in list(fluxo.caixas):
                    cv2.rectangle(img, (w - r, t), (w - l, b), cor, 2)
            ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")
            time.sleep(0.05)                # ~20 fps é de sobra

    def capturar_encoding(self, chave, tentativas=5):
        """Junta até 'tentativas' frames recentes desse totem e devolve (encoding_médio, frame) ou (None, motivo)."""
        if not self.rodando:
            return None, self.erro or "Reconhecimento ainda iniciando, tente de novo em instantes."
        fluxo = self.fluxo(chave)
        frames, melhor, pedido, visto = [], None, None, -1
        fluxo.pausado = True                # reconhecimento desse totem descansa enquanto cadastra
        try:
            limite = time.time() + 4
            while len(frames) < tentativas and time.time() < limite:
                frame, fid = fluxo.atual()
                if frame is not None and fid != visto and time.time() - fluxo.recebido_em <= QUADRO_VELHO:
                    visto = fid
                    frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    melhor = frame
                time.sleep(0.12)
            if not frames:
                return None, "A câmera do totem não está enviando imagens."
            pedido = uuid.uuid4().hex
            pronto = threading.Event()
            self._cadastros[pedido] = [pronto, None]
            self._entrada.put(("cadastro", pedido, frames), timeout=5)
            if not pronto.wait(timeout=30):
                return None, "O reconhecimento demorou demais. Tente de novo."
            enc = self._cadastros[pedido][1]
        except queue.Full:
            return None, "O reconhecimento está ocupado. Tente de novo."
        finally:
            self._cadastros.pop(pedido, None)
            fluxo.pausado = False
        if enc is None:
            return None, "Nenhum rosto único detectado. Fique sozinho e de frente para a câmera."
        return enc, melhor

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

from database import db, Aluno, Professor, registrar_presenca_totem, agora_local, hoje_local

# de onde vêm as imagens: "tablet" (câmera do navegador do tablet) ou "camera" (webcam ligada no servidor)
FONTE = os.getenv("TOTEM_FONTE", "tablet").strip().lower()
# só registra depois de ver o rosto se mexer sozinho (foto impressa tem olhos e boca parados)
PROVA_DE_VIDA = os.getenv("PROVA_DE_VIDA", "1") != "0"

TOLERANCIA = 0.50        # menor = mais rígido
CONFIRMACOES = 2         # encodings seguidos com o mesmo aluno antes de registrar...
CONFIRMA_DIRETO = 0.42   # ...a não ser que o primeiro já seja bem parecido
# o encoding (rede neural do dlib) é a parte cara: ~0,3 s num dlib com AVX, ~1,2 s num dlib sem BLAS/AVX.
# Por isso roda em processos auxiliares: a detecção e a prova de vida não param enquanto ele calcula.
# Um encoding por rosto de cada vez: na prática o primeiro já confirma (distância < CONFIRMA_DIRETO) e dois
# ao mesmo tempo disputam a CPU e atrasam os dois. Mais de um auxiliar serve para vários totens.
TRABALHADORES = max(1, int(os.getenv("FACE_TRABALHADORES", "2")))
REUSAR_CAIXA = 0.5       # durante um encoding, roda o HOG no máximo a cada 0,5 s e reaproveita a última caixa
COOLDOWN = 8.0           # segundos antes de reconhecer o MESMO aluno de novo
PAUSA_APOS_EVENTO = 0.5  # segundos "descansando" depois de qualquer registro (o próximo da fila já pode passar)
INTERVALO = 0.02         # segundos entre duas voltas do envio de frames ao processo de reconhecimento
QUADRO_VELHO = 2.0       # frame mais velho que isso não serve (tablet parou de mandar)

# quando calcular o encoding (a parte cara)
ROSTO_MINIMO = 40        # px de altura no frame reduzido; menor que isso está longe demais
TENTAR_DE_NOVO = 0.5     # rosto desconhecido: no máximo 2 encodings por segundo
REVERIFICAR = 1.5        # rosto já reconhecido: confere de novo a cada 1,5 s (percebe o próximo aluno da fila)
MESMO_ROSTO_IOU = 0.4    # sobreposição mínima entre caixas p/ considerar o mesmo rosto

# prova de vida: o aluno tem que piscar; foto impressa não pisca.
# piscada = olhos abertos -> fechados (abertura caiu pelo menos VARIACAO_VIVO) -> abertos de novo, em até JANELA_VIVO frames.
# Os limites ficam acima do ruído: numa foto parada ou tremendo na mão, a abertura medida dos olhos oscila
# 10-20% só por compressão e tremor (com 12% a foto passava); uma piscada real derruba 40-70%.
# Exigir que o olho reabra evita contar uma foto inclinada (a abertura cai e fica baixa) como piscada.
OLHO_ABERTO_MIN = 0.20
VARIACAO_VIVO = float(os.getenv("VARIACAO_VIVO", "0.30"))
REABRIU = 0.85           # reabriu = voltou a pelo menos 85% da abertura de antes da piscada
JANELA_VIVO = 8

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


def encoding_de_imagens(jpegs):
    """Encoding médio de várias fotos JPEG (cadastro de rosto do professor pela câmera do admin).
    Devolve (encoding, melhor_frame_bgr) ou (None, motivo)."""
    if face_recognition is None:
        return None, "Biblioteca face_recognition não instalada."
    achados, melhor = [], None
    for jpeg in jpegs:
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        with DLIB_LOCK:
            locs = face_recognition.face_locations(rgb, model="hog")
            if len(locs) != 1:
                continue
            achados.append(face_recognition.face_encodings(rgb, locs)[0])
        melhor = frame
    if len(achados) < 2:
        return None, "Não deu para ver bem o rosto. Fique sozinho, de frente e perto da câmera."
    return np.mean(achados, axis=0).astype(np.float64), melhor


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


def piscou(olhos):
    """True se a sequência de aberturas tem olho aberto, depois fechado e depois aberto de novo."""
    aberto, fechou = 0.0, False
    for ear in olhos:
        if not fechou:
            aberto = max(aberto, ear)
            fechou = aberto >= OLHO_ABERTO_MIN and ear <= aberto * (1 - VARIACAO_VIVO)
        elif ear >= aberto * REABRIU:
            return True
    return False


def atualizar_vivo(trilha, marcos):
    """Guarda a abertura dos olhos dos últimos frames e marca trilha['vivo'] quando o aluno pisca."""
    ear = (abertura_olhos(marcos["left_eye"]) + abertura_olhos(marcos["right_eye"])) / 2
    trilha["olhos"].append(ear)
    if piscou(trilha["olhos"]):
        trilha["vivo"] = True


def _nova_trilha(grupo="aluno"):
    return {"grupo": grupo, "aluno_id": None, "seq": 0, "confirmado": False, "t_enc": 0.0, "vivo": False,
            "registrado": False, "olhos": deque(maxlen=JANELA_VIVO),
            "token": uuid.uuid4().hex, "pendentes": 0}


def processo_encoder(pedidos, respostas):
    """Processo auxiliar: (tarefa, rgb, caixa) -> (tarefa, encoding ou None)."""
    import face_recognition as fr
    while True:
        tarefa, rgb, caixa = pedidos.get()
        if tarefa is None:
            return
        try:
            encs = fr.face_encodings(rgb, [caixa])
            respostas.put((tarefa, encs[0] if encs else None))
        except Exception as e:
            print(f"[encoder] erro: {e}")
            respostas.put((tarefa, None))


def _recorte(rgb, caixa):
    """Só a região do rosto (com folga) vai para o encoder: menos bytes entre processos."""
    t, r, b, l = caixa
    m = int(max(b - t, r - l) * 0.5)
    y0, x0 = max(0, t - m), max(0, l - m)
    pedaco = np.ascontiguousarray(rgb[y0:min(rgb.shape[0], b + m), x0:min(rgb.shape[1], r + m)])
    return pedaco, (t - y0, r - x0, b - y0, l - x0)


def processo_reconhecimento(entrada, saida, prova_de_vida=True, ampliar=1, pedidos_enc=None, respostas_enc=None):
    """Recebe frames reduzidos (RGB) de um ou mais totens e devolve onde está o rosto e de quem é.

    ampliar: quantas vezes o detector amplia a imagem (0 no frame de 640px do tablet = 3x mais rápido).
    Detecta rosto em todo frame (barato), mas só calcula o encoding (caro) quando aparece um rosto
    novo, faltam confirmações, ou chegou a hora de reverificar. Cada totem (chave) tem a sua trilha.
    grupo: "aluno" (totem liberado, registra presença) ou "prof" (totem bloqueado, professor libera).
    Mensagens: ("frame", chave, fid, rgb, grupo) | ("rostos", {grupo: (ids, encs)}) | ("cadastro", pedido, [rgb])
               ("lote", pedido, chave, [(momento, rgb)]) | ("esquecer", chave) | ("fim",)
    Resposta:  ("deteccao", chave, fid, caixa, pessoa_id, estado, novo_evento, grupo)
               ("lote", pedido, [(aluno_id, momento)]) com quem foi reconhecido (com prova de vida) nas fotos do lote
    estado: sem_rosto | longe | verificando | desconhecido | pisque | ok
    """
    import face_recognition as fr

    rostos = {}
    trilhas = {}
    tarefas = {}        # tarefa -> (chave, token da trilha, grupo, momento do frame)
    paralelo = pedidos_enc is not None

    def identificar(enc, grupo):
        ids, encs = rostos.get(grupo, ([], None))
        if not len(ids):
            return None, 1.0
        dist = np.linalg.norm(encs - enc, axis=1)
        i = int(np.argmin(dist))
        return (ids[i] if dist[i] <= TOLERANCIA else None), float(dist[i])

    def aplicar(trilha, enc, grupo, agora):
        """Junta o resultado de um encoding à trilha do rosto (confirma, troca de pessoa ou zera)."""
        aluno_id, dist = identificar(enc, grupo) if enc is not None else (None, 1.0)
        trilha["t_enc"] = agora
        if trilha["confirmado"]:
            if aluno_id != trilha["aluno_id"]:          # trocou a pessoa na frente da câmera
                trilha.update(_nova_trilha(grupo), caixa=trilha["caixa"], t_enc=agora, t_visto=trilha["t_visto"],
                              aluno_id=aluno_id, seq=1 if aluno_id else 0)
        elif aluno_id is None:
            trilha.update(aluno_id=None, seq=0)
        elif aluno_id == trilha["aluno_id"]:
            trilha["seq"] += 1
        else:
            trilha.update(aluno_id=aluno_id, seq=1)
        if trilha["aluno_id"] and (trilha["seq"] >= CONFIRMACOES or dist <= CONFIRMA_DIRETO):
            trilha["confirmado"] = True

    def marcar_registrado(trilha, agora):
        trilha["registrado"] = True
        # reconfere quem está na frente logo depois da pausa: costuma ser o próximo aluno da fila
        trilha["t_enc"] = agora - REVERIFICAR + PAUSA_APOS_EVENTO

    def receber_encodings():
        """Aplica os encodings que os processos auxiliares terminaram (descarta os de rostos que já saíram)."""
        while True:
            try:
                tarefa, enc = respostas_enc.get_nowait()
            except queue.Empty:
                return
            dono = tarefas.pop(tarefa, None)
            if dono is None:
                continue
            chave, token, grupo, momento = dono
            trilha = trilhas.get(chave)
            if trilha is None or trilha["token"] != token:
                continue
            trilha["pendentes"] = max(0, trilha["pendentes"] - 1)
            aplicar(trilha, enc, grupo, momento)
            # confirmou e já está vivo: registra agora, sem esperar o próximo frame chegar
            if trilha["confirmado"] and not trilha["registrado"] and (trilha["vivo"] or not prova_de_vida):
                marcar_registrado(trilha, time.time())
                saida.put(("deteccao", chave, trilha.get("fid"), trilha["caixa"], trilha["aluno_id"], "ok", True, grupo))

    def processar(chave, rgb, grupo, agora, sincrono=False):
        """Um quadro de um totem -> (caixa, pessoa_id, estado, novo_evento). agora = hora do quadro (segundos):
        a de agora para o totem ao vivo, a da foto para a fila offline (sincrono=True: calcula o encoding aqui)."""
        trilha = trilhas.get(chave)
        # com um encoding em andamento, o rosto quase não sai do lugar: reaproveita a caixa e só roda o HOG
        # de vez em quando, para não disputar CPU com o encoder (a prova de vida segue em todo frame)
        if (paralelo and not sincrono and trilha is not None and trilha["pendentes"] and trilha["grupo"] == grupo
                and agora - trilha.get("t_hog", 0) < REUSAR_CAIXA):
            locs, rodou_hog = [trilha["caixa"]], False
        else:
            locs, rodou_hog = fr.face_locations(rgb, ampliar, model="hog"), True
            if not locs:
                trilhas.pop(chave, None)
                return None, None, "sem_rosto", False

        caixa = max(locs, key=lambda c: (c[2] - c[0]) * (c[1] - c[3]))
        # rosto novo, outro grupo, outro lugar na imagem ou mais de 5 s sem ver ninguem: comeca de novo
        if (trilha is None or trilha["grupo"] != grupo or _iou(caixa, trilha["caixa"]) < MESMO_ROSTO_IOU
                or abs(agora - trilha.get("t_visto", agora)) > 5):
            trilha = trilhas[chave] = _nova_trilha(grupo)
        if rodou_hog:
            trilha["t_hog"] = agora
        trilha["caixa"], trilha["t_visto"] = caixa, agora

        perto = (caixa[2] - caixa[0]) >= ROSTO_MINIMO
        if not perto:
            return caixa, None, "longe", False

        # prova de vida: mede a abertura dos olhos em todo frame até o aluno piscar
        if prova_de_vida and not trilha["vivo"]:
            marcos = fr.face_landmarks(rgb, [caixa])
            if marcos and "left_eye" in marcos[0] and "right_eye" in marcos[0]:
                atualizar_vivo(trilha, marcos[0])

        if sincrono or not paralelo:
            if trilha["confirmado"]:
                precisa = agora - trilha["t_enc"] >= REVERIFICAR
            elif trilha["seq"] > 0:
                precisa = True                                  # falta confirmar
            else:
                precisa = agora - trilha["t_enc"] >= TENTAR_DE_NOVO
            if precisa:
                aplicar(trilha, fr.face_encodings(rgb, [caixa])[0], grupo, agora)
        else:
            # pede encodings aos auxiliares sem esperar; enquanto isso segue detectando e medindo a prova de vida
            if trilha["confirmado"]:
                pedir = not trilha["pendentes"] and agora - trilha["t_enc"] >= REVERIFICAR
            elif trilha["t_enc"] and trilha["aluno_id"] is None:   # desconhecido: tenta de novo com calma
                pedir = not trilha["pendentes"] and agora - trilha["t_enc"] >= TENTAR_DE_NOVO
            else:                                                  # rosto novo ou falta confirmar: já
                pedir = not trilha["pendentes"]
            for velha in [t for t, d in tarefas.items() if agora - d[3] > 10]:   # resposta que nunca veio
                _, token, _, _ = tarefas.pop(velha)
                if token == trilha["token"]:
                    trilha["pendentes"] = max(0, trilha["pendentes"] - 1)
            if pedir and len(tarefas) < TRABALHADORES * 2:
                tarefa = uuid.uuid4().hex
                pedaco, caixa_rel = _recorte(rgb, caixa)
                try:
                    pedidos_enc.put_nowait((tarefa, pedaco, caixa_rel))
                    tarefas[tarefa] = (chave, trilha["token"], grupo, agora)
                    trilha["pendentes"] += 1
                except queue.Full:
                    pass

        novo_evento = False
        if trilha["confirmado"] and not trilha["registrado"]:
            if trilha["vivo"] or not prova_de_vida:
                marcar_registrado(trilha, agora)
                novo_evento = True
                estado = "ok"
            else:
                estado = "pisque"
        elif trilha["registrado"]:
            estado = "ok"
        elif trilha["t_enc"] and trilha["aluno_id"] is None:
            estado = "desconhecido"
        elif prova_de_vida and not trilha["vivo"]:
            estado = "pisque"                   # já pede a piscada enquanto o encoding calcula
        else:
            estado = "verificando"
        return caixa, trilha["aluno_id"], estado, novo_evento

    while True:
        if paralelo:
            receber_encodings()
            try:
                msg = entrada.get(timeout=0.03)
            except queue.Empty:
                continue
        else:
            msg = entrada.get()
        tipo = msg[0]
        try:
            if tipo == "fim":
                return
            if tipo == "rostos":
                rostos = msg[1]
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

            if tipo == "lote":
                # fila offline do tablet: fotos antigas em ordem, cada uma com a hora em que foi tirada
                _, pedido, chave, quadros = msg
                eventos = []
                for momento, rgb in quadros:
                    _, pessoa_id, _, novo_evento = processar(chave, rgb, "aluno", momento, sincrono=True)
                    if novo_evento:
                        eventos.append((pessoa_id, momento))
                saida.put(("lote", pedido, eventos))
                continue

            _, chave, fid, rgb, grupo = msg
            if paralelo:
                receber_encodings()             # resultado que chegou enquanto o frame esperava
            caixa, pessoa_id, estado, novo_evento = processar(chave, rgb, grupo, time.time())
            if chave in trilhas:
                trilhas[chave]["fid"] = fid     # frame mais recente desse rosto (para a foto do registro)
            saida.put(("deteccao", chave, fid, caixa, pessoa_id, estado, novo_evento, grupo))
        except Exception as e:                    # uma falha não pode matar o processo
            print(f"[reconhecimento] erro: {e}")
            if tipo in ("cadastro", "lote"):
                saida.put((tipo, msg[1], None))


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
        self.grupo = "aluno"         # "prof" enquanto o totem está bloqueado esperando um professor
        self.professor_liberou = None   # id do professor reconhecido no totem bloqueado

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
        # tablet manda 640px: usa inteiro e detecta sem ampliar (30 ms); webcam reduz para 320px e amplia 1x
        self.escala, self.ampliar = (1.0, 0) if fonte == "tablet" else (0.5, 1)
        self.cap = None
        self.rodando = False
        self.iniciando = False
        self.erro = None
        self._start_lock = threading.Lock()
        self._ultima_tentativa = 0.0
        self.fluxos = {}
        self._fluxos_lock = threading.Lock()
        self.rostos = {}             # grupo -> (ids, encs)
        self.ultimo_evento = {}      # aluno_id -> timestamp

        self._proc = None
        self._entrada = self._saida = None
        self._encoders = []          # processos auxiliares que calculam os encodings
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
        for p in self._encoders:               # reinício: os auxiliares antigos saem junto
            if p.is_alive():
                p.terminate()
        self._entrada = ctx.Queue(maxsize=2)   # fila curta: frame velho é descartado, não acumula atraso
        self._saida = ctx.Queue()
        pedidos_enc, respostas_enc = ctx.Queue(maxsize=TRABALHADORES * 2), ctx.Queue()
        self._encoders = [ctx.Process(target=processo_encoder, args=(pedidos_enc, respostas_enc),
                                      name=f"encoder-facial-{i + 1}", daemon=True) for i in range(TRABALHADORES)]
        for p in self._encoders:
            p.start()
        self._proc = ctx.Process(target=processo_reconhecimento,
                                 args=(self._entrada, self._saida, PROVA_DE_VIDA, self.ampliar, pedidos_enc, respostas_enc),
                                 name="reconhecimento-facial", daemon=True)
        self._proc.start()
        self.recarregar()

    def recarregar(self):
        """Carrega os rostos de alunos e professores do banco e manda para o processo de reconhecimento."""
        rostos = {}
        with self.app.app_context():
            for grupo, modelo in (("aluno", Aluno), ("prof", Professor)):
                pessoas = modelo.query.filter(modelo.face_encoding.isnot(None)).all()
                encs = [np.frombuffer(p.face_encoding, dtype=np.float64) for p in pessoas]
                rostos[grupo] = ([p.id for p in pessoas], np.array(encs) if encs else np.empty((0, 128)))
        self.rostos = rostos
        if self._proc is not None and self._proc.is_alive():
            self._entrada.put(("rostos", self.rostos))

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

    def receber_frame(self, chave, jpeg, grupo="aluno"):
        """Modo tablet: guarda a foto que o navegador mandou e devolve o último resultado desse totem.
        grupo "prof" = totem bloqueado procurando um professor para liberar."""
        self.iniciar()
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("imagem inválida")
        if max(frame.shape[:2]) > 960:          # tablet que ignorou o tamanho pedido
            f = 960 / max(frame.shape[:2])
            frame = cv2.resize(frame, (0, 0), fx=f, fy=f)
        fluxo = self.fluxo(chave)
        if fluxo.grupo != grupo:
            fluxo.grupo, fluxo.estado, fluxo.caixas = grupo, "sem_rosto", []
        fluxo.guardar(frame)
        caixa =fluxo.caixas[0][:4] if fluxo.caixas else None
        return {"caixa": caixa, "estado": fluxo.estado, "largura": frame.shape[1], "altura": frame.shape[0],
                "pronto": self.rodando, "erro": self.erro}

    def _alimentar(self):
        """Manda o frame mais novo (reduzido) de cada totem para o processo de reconhecimento."""
        while self.rodando:
            time.sleep(INTERVALO)
            if not self._proc.is_alive() or not all(p.is_alive() for p in self._encoders):
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
                pequeno = frame if self.escala == 1.0 else cv2.resize(frame, (0, 0), fx=self.escala, fy=self.escala)
                rgb = cv2.cvtColor(pequeno, cv2.COLOR_BGR2RGB)
                try:
                    self._entrada.put_nowait(("frame", chave, fid, rgb, fluxo.grupo))
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
                if msg[0] in ("cadastro", "lote"):
                    _, pedido, enc = msg
                    if pedido in self._cadastros:
                        self._cadastros[pedido][1] = enc
                        self._cadastros[pedido][0].set()
                    continue

                _, chave, fid, caixa, aluno_id, estado, novo_evento, grupo = msg
                fluxo = self.fluxo(chave)
                if grupo != fluxo.grupo:            # resultado de antes do totem trocar de modo
                    continue
                fluxo.estado, fluxo.aluno_id = estado, aluno_id
                if caixa is None:
                    fluxo.caixas = []
                    continue
                t, r, b, l = [int(v / self.escala) for v in caixa]
                fluxo.caixas = [(t, r, b, l, (0, 200, 0) if aluno_id else (0, 0, 255))]
                if grupo == "prof":
                    if novo_evento:
                        fluxo.professor_liberou = aluno_id
                    continue
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
            status, ja, info = registrar_presenca_totem(aluno)
            if frame is not None:
                self._atualizar_foto(aluno, frame, caixa)
            agora = agora_local()
            fluxo.eventos.append({
                "nome": aluno.nome,
                "matricula": aluno.matricula,
                "foto": aluno.foto,
                "status": status,
                "ja_registrado": ja,
                "mensagem": info.get("mensagem", ""),
                "data": hoje_local().strftime("%d/%m/%Y"),
                "hora": agora.strftime("%H:%M:%S"),
            })
            print(f"[totem] {aluno.nome} -> {status}{' (já registrado)' if ja else ''} {info.get('mensagem', '')}")

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
    def professor_reconhecido(self, chave):
        """Id do professor que acabou de olhar para o totem bloqueado (entregue uma vez só)."""
        fluxo = self.fluxo(chave)
        pid, fluxo.professor_liberou = fluxo.professor_liberou, None
        return pid

    def esquecer(self, chave):
        """Apaga as imagens e a trilha de um totem (ex.: a chave provisória de um aparelho recém-liberado)."""
        with self._fluxos_lock:
            self.fluxos.pop(chave, None)
        if self._proc is not None and self._proc.is_alive():
            try:
                self._entrada.put_nowait(("esquecer", chave))
            except queue.Full:
                pass

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

    def processar_lote(self, chave, itens):
        """Fila offline do tablet: [(momento, jpeg)] em ordem -> [(aluno_id, momento)] de quem foi reconhecido,
        ou None se o reconhecimento estiver ocupado. momento = hora da foto em segundos, usada nas regras de tempo."""
        if not self.rodando:
            return None
        quadros = []
        for momento, jpeg in itens:
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            if max(frame.shape[:2]) > 960:
                f = 960 / max(frame.shape[:2])
                frame = cv2.resize(frame, (0, 0), fx=f, fy=f)
            pequeno = frame if self.escala == 1.0 else cv2.resize(frame, (0, 0), fx=self.escala, fy=self.escala)
            quadros.append((momento, cv2.cvtColor(pequeno, cv2.COLOR_BGR2RGB)))
        pedido = uuid.uuid4().hex
        pronto = threading.Event()
        self._cadastros[pedido] = [pronto, None]
        try:
            self._entrada.put(("lote", pedido, chave, quadros), timeout=10)
            if not pronto.wait(timeout=120):
                return None
            return self._cadastros[pedido][1]
        except queue.Full:
            return None
        finally:
            self._cadastros.pop(pedido, None)

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

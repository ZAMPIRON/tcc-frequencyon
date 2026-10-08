import os
import threading
import time
from collections import deque
import cv2
import numpy as np

try:
    import face_recognition
except ImportError:  # permite subir o site sem a lib (o totem fica indisponível)
    face_recognition = None

from database import db, Aluno, registrar_presenca_totem, agora_local, hoje_local

TOLERANCIA = 0.50        # menor = mais rígido
ESCALA = 0.5             # reduz o frame p/ detectar (menor = mais rápido)
CONFIRMACOES = 2         # frames seguidos com o mesmo aluno antes de registrar
COOLDOWN = 8.0           # segundos antes de reconhecer o MESMO aluno de novo
PAUSA_APOS_EVENTO = 3.0  # segundos "descansando" depois de qualquer registro
INTERVALO = 0.15         # segundos mínimos entre dois reconhecimentos

DLIB_LOCK = threading.Lock()   # só uma thread por vez pode usar o dlib


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


class Totem:
    def __init__(self, app, camera=0):
        self.app, self.camera = app, camera
        self.cap = None
        self.rodando = False
        self.iniciando = False
        self.erro = None
        self._start_lock = threading.Lock()
        self._ultima_tentativa = 0.0
        self.lock = threading.Lock()
        self.frame = None            # último frame cru da câmera (BGR)
        self.frame_id = 0
        self.caixas = []             # [(top,right,bottom,left,cor)]
        self.eventos = deque(maxlen=20)
        self.ids, self.encs = [], np.empty((0, 128))
        self.ultimo_evento = {}      # aluno_id -> timestamp
        self._livre_em = 0.0         # não reconhece antes desse instante
        self._pausar = threading.Event()   # pausa o reconhecimento (cadastro de face)

    # ---------- ciclo de vida ----------
    def iniciar(self):
        """Não bloqueia: abre a câmera em segundo plano. Pode ser chamado à vontade."""
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
            self.cap, self.erro = cap, None
            self.recarregar()
            self.rodando = True
            threading.Thread(target=self._capturar, daemon=True).start()
            threading.Thread(target=self._reconhecer, daemon=True).start()
        except Exception as e:                      # nunca derruba o servidor
            self.erro = f"Erro ao iniciar a câmera: {e}"
        finally:
            self.iniciando = False

    def recarregar(self):
        """Carrega os rostos do banco para a memória (rápido na hora de comparar)."""
        with self.app.app_context():
            alunos = Aluno.query.filter(Aluno.face_encoding.isnot(None)).all()
            ids = [a.id for a in alunos]
            encs = [np.frombuffer(a.face_encoding, dtype=np.float64) for a in alunos]
        self.ids = ids
        self.encs = np.array(encs) if encs else np.empty((0, 128))

    # ---------- threads ----------
    def _capturar(self):
        falhas = 0
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
            with self.lock:
                self.frame = frame
                self.frame_id += 1

    def _frame_atual(self):
        with self.lock:
            return (None, 0) if self.frame is None else (self.frame.copy(), self.frame_id)

    @staticmethod
    def _maior_rosto(locs):
        return max(locs, key=lambda l: (l[2] - l[0]) * (l[1] - l[3]))

    def _reconhecer(self):
        ultimo_id, seq, visto = None, 0, -1
        while self.rodando:
            time.sleep(INTERVALO)
            try:
                if self._pausar.is_set() or time.time() < self._livre_em:
                    continue
                frame, fid = self._frame_atual()
                if frame is None or fid == visto:
                    continue
                visto = fid

                rgb = cv2.cvtColor(cv2.resize(frame, (0, 0), fx=ESCALA, fy=ESCALA),
                                   cv2.COLOR_BGR2RGB)
                with DLIB_LOCK:
                    locs = face_recognition.face_locations(rgb, model="hog")
                    if not locs:
                        self.caixas, ultimo_id, seq = [], None, 0
                        continue
                    loc = self._maior_rosto(locs)
                    enc = face_recognition.face_encodings(rgb, [loc])[0]

                t, r, b, l = [int(v / ESCALA) for v in loc]
                aluno_id = None
                if len(self.ids):
                    dist = np.linalg.norm(self.encs - enc, axis=1)
                    i = int(np.argmin(dist))
                    if dist[i] <= TOLERANCIA:
                        aluno_id = self.ids[i]

                if aluno_id is None:
                    self.caixas = [(t, r, b, l, (0, 0, 255))]
                    ultimo_id, seq = None, 0
                    continue

                self.caixas = [(t, r, b, l, (0, 200, 0))]
                seq = seq + 1 if aluno_id == ultimo_id else 1
                ultimo_id = aluno_id
                if seq >= CONFIRMACOES:
                    seq = 0
                    if time.time() - self.ultimo_evento.get(aluno_id, 0) > COOLDOWN:
                        self.ultimo_evento[aluno_id] = time.time()
                        self._livre_em = time.time() + PAUSA_APOS_EVENTO
                        self._registrar(aluno_id)
            except Exception as e:                  # uma falha não pode matar a thread
                print(f"[totem] erro no reconhecimento: {e}")
                time.sleep(0.5)

    def _registrar(self, aluno_id):
        with self.app.app_context():
            aluno = db.session.get(Aluno, aluno_id)
            if not aluno:
                return
            status, ja = registrar_presenca_totem(aluno)
            agora = agora_local()
            self.eventos.append({
                "nome": aluno.nome,
                "matricula": aluno.matricula,
                "foto": aluno.foto,
                "status": status,
                "ja_registrado": ja,
                "data": hoje_local().strftime("%d/%m/%Y"),
                "hora": agora.strftime("%H:%M:%S"),
            })
            print(f"[totem] {aluno.nome} -> {status}{' (já registrado hoje)' if ja else ''}")

    # ---------- API usada pelas rotas ----------
    def proximo_evento(self):
        try:
            return self.eventos.popleft()
        except IndexError:
            return None

    def stream(self):
        """Gerador MJPEG para <img src='/video_feed'>. Só codifica quando há frame novo."""
        ultimo = -1
        while True:
            frame, fid = self._frame_atual()
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
                for (t, r, b, l, cor) in list(self.caixas):
                    cv2.rectangle(img, (w - r, t), (w - l, b), cor, 2)
            ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")
            time.sleep(0.05)                # ~20 fps é de sobra

    def capturar_encoding(self, tentativas=5):
        """Tira até 'tentativas' fotos e devolve (encoding_médio, frame) ou (None, motivo)."""
        if not self.rodando:
            return None, self.erro or "Câmera ainda iniciando, tente de novo em instantes."
        encs, melhor = [], None
        self._pausar.set()                  # reconhecimento descansa enquanto cadastra
        try:
            for _ in range(tentativas):
                frame, _fid = self._frame_atual()
                if frame is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    with DLIB_LOCK:
                        locs = face_recognition.face_locations(rgb, model="hog")
                        if len(locs) == 1:
                            encs.append(face_recognition.face_encodings(rgb, locs)[0])
                            melhor = frame
                time.sleep(0.15)
        finally:
            self._pausar.clear()
        if not encs:
            return None, "Nenhum rosto único detectado. Fique sozinho e de frente para a câmera."
        return np.mean(encs, axis=0).astype(np.float64), melhor
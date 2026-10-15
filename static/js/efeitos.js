/* =====================================================================
   FrequencyON — efeitos de interface (sem dependências)
   Expõe window.FO: toast, pedir, confete, explosao, som
   ===================================================================== */
(function () {
    "use strict";

    const FO = (window.FO = window.FO || {});
    const reduzMovimento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* ---------------- toasts ---------------- */
    const ICONES_TOAST = {
        success: "bi-check-lg",
        danger: "bi-x-lg",
        warning: "bi-exclamation-lg",
        info: "bi-info-lg",
    };

    FO.toast = function (mensagem, tipo = "info", ms = 4200) {
        let caixa = document.querySelector(".fo-toasts");
        if (!caixa) {
            caixa = document.createElement("div");
            caixa.className = "fo-toasts";
            caixa.setAttribute("aria-live", "polite");
            document.body.appendChild(caixa);
        }
        if (!ICONES_TOAST[tipo]) tipo = "info";
        const el = document.createElement("div");
        el.className = "fo-toast";
        el.setAttribute("role", tipo === "danger" ? "alert" : "status");
        el.innerHTML = `
            <span class="fo-toast-icone ${tipo}"><i class="bi ${ICONES_TOAST[tipo]}"></i></span>
            <div class="fo-toast-texto flex-grow-1 small fw-semibold"></div>
            <button type="button" class="btn-close btn-sm" aria-label="Fechar"></button>
            <span class="fo-toast-tempo ${tipo}"></span>`;
        // a duração da barrinha acompanha o tempo do toast
        el.querySelector(".fo-toast-tempo").style.animationDuration = ms + "ms";
        el.querySelector(".fo-toast-texto").textContent = mensagem;
        const fechar = () => {
            el.classList.add("saindo");
            setTimeout(() => el.remove(), 350);
        };
        el.querySelector(".btn-close").addEventListener("click", fechar);
        caixa.appendChild(el);
        setTimeout(fechar, ms);
        return el;
    };

    /* ---------------- modal de pergunta (substitui prompt) ---------------- */
    FO.pedir = function ({ titulo = "Confirmação", texto = "", tipo = "text", placeholder = "", confirmar = "Confirmar", icone = "bi-shield-lock" } = {}) {
        return new Promise((resolve) => {
            if (!window.bootstrap) { resolve(window.prompt(texto)); return; }
            const wrap = document.createElement("div");
            wrap.className = "modal fade";
            wrap.tabIndex = -1;
            wrap.innerHTML = `
              <div class="modal-dialog modal-dialog-centered">
                <form class="modal-content">
                  <div class="modal-body p-4 text-center">
                    <div class="fo-logo-icone tamanho-56 flutuando mx-auto mb-3"><i class="bi ${icone}"></i></div>
                    <h5 class="fw-bold mb-1"></h5>
                    <p class="text-muted small mb-3"></p>
                    <input class="form-control form-control-lg text-center" required>
                  </div>
                  <div class="modal-footer border-0 pt-0 justify-content-center gap-2">
                    <button type="button" class="btn btn-light px-4" data-bs-dismiss="modal">Cancelar</button>
                    <button type="submit" class="btn btn-primary px-4"></button>
                  </div>
                </form>
              </div>`;
            wrap.querySelector("h5").textContent = titulo;
            wrap.querySelector("p").textContent = texto;
            const input = wrap.querySelector("input");
            input.type = tipo;
            input.placeholder = placeholder;
            wrap.querySelector("button[type=submit]").textContent = confirmar;
            document.body.appendChild(wrap);
            const modal = new bootstrap.Modal(wrap);
            let valor = null;
            wrap.querySelector("form").addEventListener("submit", (e) => {
                e.preventDefault();
                valor = input.value.trim() || null;
                modal.hide();
            });
            wrap.addEventListener("shown.bs.modal", () => input.focus());
            wrap.addEventListener("hidden.bs.modal", () => { wrap.remove(); resolve(valor); });
            modal.show();
        });
    };

    /* ---------------- partículas: confete e explosão ---------------- */
    let fx = null;
    function canvasFx() {
        if (fx) return fx;
        const c = document.createElement("canvas");
        c.className = "fo-fx-canvas";
        document.body.appendChild(c);
        const ctx = c.getContext("2d");
        const pecas = [];
        const ajustar = () => {
            const dpr = Math.min(window.devicePixelRatio || 1, 2);
            c.width = innerWidth * dpr;
            c.height = innerHeight * dpr;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        };
        ajustar();
        addEventListener("resize", ajustar);
        let rodando = false;
        const loop = () => {
            ctx.clearRect(0, 0, innerWidth, innerHeight);
            for (let i = pecas.length - 1; i >= 0; i--) {
                const p = pecas[i];
                p.vy += p.g;
                p.vx *= p.atrito;
                p.vy *= p.atrito;
                p.x += p.vx;
                p.y += p.vy;
                p.rot += p.vr;
                p.vida -= 1;
                const alfa = Math.max(0, Math.min(1, p.vida / 40));
                ctx.save();
                ctx.globalAlpha = alfa;
                ctx.translate(p.x, p.y);
                ctx.rotate(p.rot);
                ctx.fillStyle = p.cor;
                if (p.forma === "circulo") {
                    ctx.beginPath();
                    ctx.arc(0, 0, p.tam / 2, 0, Math.PI * 2);
                    ctx.fill();
                } else {
                    ctx.fillRect(-p.tam / 2, -p.tam / 4, p.tam, p.tam / 2);
                }
                ctx.restore();
                if (p.vida <= 0 || p.y > innerHeight + 40) pecas.splice(i, 1);
            }
            if (pecas.length) requestAnimationFrame(loop);
            else rodando = false;
        };
        fx = {
            add(lista) {
                pecas.push(...lista);
                if (!rodando) { rodando = true; requestAnimationFrame(loop); }
            },
        };
        return fx;
    }

    const CORES = ["#5b8cff", "#a26bff", "#ff4fd8", "#22d3ee", "#22e19a", "#ffc23d"];

    FO.confete = function ({ x = innerWidth / 2, y = innerHeight / 3, quantidade = 140, cores = CORES } = {}) {
        if (reduzMovimento) return;
        const lista = [];
        for (let i = 0; i < quantidade; i++) {
            const ang = Math.random() * Math.PI * 2;
            const vel = 4 + Math.random() * 9;
            lista.push({
                x, y,
                vx: Math.cos(ang) * vel,
                vy: Math.sin(ang) * vel - 6,
                g: 0.22, atrito: 0.985,
                rot: Math.random() * 6, vr: (Math.random() - 0.5) * 0.4,
                tam: 7 + Math.random() * 7,
                cor: cores[(Math.random() * cores.length) | 0],
                forma: Math.random() < 0.3 ? "circulo" : "fita",
                vida: 110 + Math.random() * 60,
            });
        }
        canvasFx().add(lista);
    };

    FO.explosao = function (el, cor) {
        if (reduzMovimento || !el) return;
        const r = el.getBoundingClientRect();
        const lista = [];
        for (let i = 0; i < 14; i++) {
            const ang = (Math.PI * 2 * i) / 14;
            const vel = 2 + Math.random() * 2.5;
            lista.push({
                x: r.left + r.width / 2, y: r.top + r.height / 2,
                vx: Math.cos(ang) * vel, vy: Math.sin(ang) * vel,
                g: 0.05, atrito: 0.93, rot: 0, vr: 0,
                tam: 4 + Math.random() * 3, cor: cor || CORES[i % CORES.length],
                forma: "circulo", vida: 34,
            });
        }
        canvasFx().add(lista);
    };

    /* ---------------- som curto (WebAudio) ---------------- */
    let audioCtx = null;
    FO.som = function (tipo = "ok") {
        try {
            audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
            const notas = { ok: [880, 1320], aviso: [520, 440], erro: [300, 220] }[tipo] || [880];
            notas.forEach((freq, i) => {
                const o = audioCtx.createOscillator();
                const g = audioCtx.createGain();
                o.type = "sine";
                o.frequency.value = freq;
                const t0 = audioCtx.currentTime + i * 0.12;
                g.gain.setValueAtTime(0.0001, t0);
                g.gain.exponentialRampToValueAtTime(0.18, t0 + 0.02);
                g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.25);
                o.connect(g).connect(audioCtx.destination);
                o.start(t0);
                o.stop(t0 + 0.3);
            });
        } catch (e) { /* áudio indisponível */ }
    };

    /* ---------------- formulários: spinner no envio ---------------- */
    function iniciarFormularios() {
        document.addEventListener("submit", (e) => {
            const form = e.target;
            if (e.defaultPrevented || form.hasAttribute("data-fo-sem-spinner")) return;
            const btn = form.querySelector('button[type="submit"], button:not([type])');
            if (!btn || btn.dataset.foCarregando) return;
            btn.dataset.foCarregando = "1";
            btn.dataset.foHtml = btn.innerHTML;
            btn.style.width = btn.offsetWidth + "px";
            btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
        });
        // voltar pelo histórico (bfcache) devolve o texto original do botão
        window.addEventListener("pageshow", () => {
            document.querySelectorAll("[data-fo-carregando]").forEach((btn) => {
                btn.innerHTML = btn.dataset.foHtml;
                btn.style.width = "";
                delete btn.dataset.foCarregando;
            });
        });
    }

    /* ---------------- start ---------------- */
    function iniciar() {
        iniciarFormularios();
        // confete e som só no totem; os painéis ficam sóbrios
        if (!document.body.classList.contains("totem")) {
            FO.confete = FO.explosao = FO.som = function () {};
        }
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
    else iniciar();
})();

/* =====================================================================
   FrequencyON — efeitos de interface (sem dependências)
   Expõe window.FO: toast, pedir, confete, explosao, particulas, setTema
   ===================================================================== */
(function () {
    "use strict";

    const FO = (window.FO = window.FO || {});
    const html = document.documentElement;
    const reduzMovimento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ehToque = window.matchMedia("(hover: none)").matches;

    /* ---------------- tema ---------------- */
    FO.tema = () => html.getAttribute("data-bs-theme") || "dark";

    FO.setTema = function (tema) {
        html.setAttribute("data-bs-theme", tema);
        try { localStorage.setItem("fo-tema", tema); } catch (e) { /* sem storage */ }
        atualizarBotoesTema();
        document.dispatchEvent(new CustomEvent("fo:tema", { detail: tema }));
    };

    function atualizarBotoesTema() {
        document.querySelectorAll("[data-fo-theme-toggle]").forEach((b) => {
            b.innerHTML = FO.tema() === "dark"
                ? '<i class="bi bi-sun-fill"></i>'
                : '<i class="bi bi-moon-stars-fill"></i>';
            b.setAttribute("aria-label", FO.tema() === "dark" ? "Usar tema claro" : "Usar tema escuro");
            b.title = b.getAttribute("aria-label");
        });
    }

    function iniciarTema() {
        if (!document.querySelector("[data-fo-theme-toggle]") && !document.body.hasAttribute("data-fo-sem-tema")) {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "fo-theme-btn flutuante";
            b.setAttribute("data-fo-theme-toggle", "");
            document.body.appendChild(b);
        }
        document.addEventListener("click", (e) => {
            const b = e.target.closest("[data-fo-theme-toggle]");
            if (!b) return;
            const r = b.getBoundingClientRect();
            const novo = FO.tema() === "dark" ? "light" : "dark";
            // transição circular a partir do botão, quando o navegador suporta
            if (document.startViewTransition && !reduzMovimento) {
                html.style.setProperty("--fo-vt-x", r.left + r.width / 2 + "px");
                html.style.setProperty("--fo-vt-y", r.top + r.height / 2 + "px");
                document.startViewTransition(() => FO.setTema(novo));
            } else {
                FO.setTema(novo);
            }
        });
        atualizarBotoesTema();
    }

    /* ---------------- contadores animados ---------------- */
    function animarNumero(el) {
        if (el.dataset.foContado) return;
        el.dataset.foContado = "1";
        const original = el.textContent.trim();
        const m = original.match(/-?\d+(?:[.,]\d+)?/);
        if (!m) return;
        const alvo = parseFloat(m[0].replace(",", "."));
        const casas = (m[0].split(/[.,]/)[1] || "").length;
        const antes = original.slice(0, m.index);
        const depois = original.slice(m.index + m[0].length);
        if (reduzMovimento || alvo === 0) return;
        const duracao = 1400;
        const inicio = performance.now();
        const passo = (agora) => {
            const t = Math.min(1, (agora - inicio) / duracao);
            const e = t === 1 ? 1 : 1 - Math.pow(2, -10 * t); // easeOutExpo
            el.textContent = antes + (alvo * e).toFixed(casas) + depois;
            if (t < 1) requestAnimationFrame(passo);
        };
        requestAnimationFrame(passo);
    }
    FO.contar = animarNumero;

    /* ---------------- reveal ao rolar ---------------- */
    let observador = null;
    function iniciarReveal() {
        const alvos = document.querySelectorAll("[data-fo-reveal], main .card, .fo-reveal-auto");
        const contadores = document.querySelectorAll("[data-countup]");
        if (!("IntersectionObserver" in window)) {
            contadores.forEach(animarNumero);
            return;
        }
        observador = new IntersectionObserver((entradas) => {
            entradas.forEach((en) => {
                if (!en.isIntersecting) return;
                const el = en.target;
                if (el.hasAttribute("data-countup")) animarNumero(el);
                else el.classList.add("fo-in");
                observador.unobserve(el);
            });
        }, { threshold: 0.08, rootMargin: "0px 0px -30px 0px" });

        // atraso escalonado por grupo de irmãos
        const grupos = new Map();
        alvos.forEach((el) => {
            if (el.closest(".modal") || el.classList.contains("fo-no-reveal")) return;
            const pai = el.parentElement && el.parentElement.parentElement;
            const i = grupos.get(pai) || 0;
            grupos.set(pai, i + 1);
            el.style.setProperty("--fo-d", Math.min(i, 8) * 80 + "ms");
            el.classList.add("fo-reveal");
            observador.observe(el);
        });
        contadores.forEach((el) => observador.observe(el));
    }

    /* ---------------- brilho que segue o mouse ---------------- */
    function iniciarSpotlight() {
        if (ehToque) return;
        document.addEventListener("pointermove", (e) => {
            const card = e.target.closest && e.target.closest(".card, .fo-glass");
            if (!card) return;
            const r = card.getBoundingClientRect();
            card.style.setProperty("--mx", e.clientX - r.left + "px");
            card.style.setProperty("--my", e.clientY - r.top + "px");
        }, { passive: true });
    }

    /* ---------------- tilt 3D ---------------- */
    function iniciarTilt() {
        if (ehToque || reduzMovimento) return;
        document.querySelectorAll("[data-tilt]").forEach((el) => {
            const forca = parseFloat(el.dataset.tilt) || 10;
            el.style.transformStyle = "preserve-3d";
            el.addEventListener("pointermove", (e) => {
                const r = el.getBoundingClientRect();
                const x = (e.clientX - r.left) / r.width - 0.5;
                const y = (e.clientY - r.top) / r.height - 0.5;
                el.style.transition = "transform .08s linear";
                el.style.transform = `perspective(900px) rotateX(${-y * forca}deg) rotateY(${x * forca}deg) translateY(-6px)`;
            });
            el.addEventListener("pointerleave", () => {
                el.style.transition = "transform .6s cubic-bezier(.2,.8,.2,1)";
                el.style.transform = "";
            });
        });
    }

    /* ---------------- botões magnéticos ---------------- */
    function iniciarMagnetico() {
        if (ehToque || reduzMovimento) return;
        document.querySelectorAll("[data-magnetic]").forEach((el) => {
            el.addEventListener("pointermove", (e) => {
                const r = el.getBoundingClientRect();
                const x = e.clientX - r.left - r.width / 2;
                const y = e.clientY - r.top - r.height / 2;
                el.style.transform = `translate(${x * 0.18}px, ${y * 0.25}px)`;
            });
            el.addEventListener("pointerleave", () => { el.style.transform = ""; });
        });
    }

    /* ---------------- ripple ---------------- */
    function iniciarRipple() {
        document.addEventListener("pointerdown", (e) => {
            const btn = e.target.closest(".btn, [data-ripple]");
            if (!btn || btn.disabled) return;
            const r = btn.getBoundingClientRect();
            const tam = Math.max(r.width, r.height);
            const onda = document.createElement("span");
            onda.className = "fo-ripple";
            onda.style.width = onda.style.height = tam + "px";
            onda.style.left = e.clientX - r.left - tam / 2 + "px";
            onda.style.top = e.clientY - r.top - tam / 2 + "px";
            btn.appendChild(onda);
            setTimeout(() => onda.remove(), 700);
        });
    }

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

    /* ---------------- rede de partículas (fundo) ---------------- */
    FO.particulas = function (canvas, { densidade = 0.00009 } = {}) {
        if (!canvas || reduzMovimento) return;
        const ctx = canvas.getContext("2d");
        let pontos = [];
        let mouse = { x: -999, y: -999 };
        const ajustar = () => {
            const dpr = Math.min(window.devicePixelRatio || 1, 2);
            canvas.width = canvas.offsetWidth * dpr;
            canvas.height = canvas.offsetHeight * dpr;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            const n = Math.min(110, Math.floor(canvas.offsetWidth * canvas.offsetHeight * densidade));
            pontos = Array.from({ length: n }, () => ({
                x: Math.random() * canvas.offsetWidth,
                y: Math.random() * canvas.offsetHeight,
                vx: (Math.random() - 0.5) * 0.45,
                vy: (Math.random() - 0.5) * 0.45,
                r: 1 + Math.random() * 1.8,
            }));
        };
        ajustar();
        addEventListener("resize", ajustar);
        addEventListener("pointermove", (e) => {
            const r = canvas.getBoundingClientRect();
            mouse = { x: e.clientX - r.left, y: e.clientY - r.top };
        }, { passive: true });
        const desenhar = () => {
            const w = canvas.offsetWidth, h = canvas.offsetHeight;
            const escuro = FO.tema() === "dark";
            const base = escuro ? "160,180,255" : "70,90,200";
            ctx.clearRect(0, 0, w, h);
            for (const p of pontos) {
                p.x += p.vx; p.y += p.vy;
                if (p.x < 0 || p.x > w) p.vx *= -1;
                if (p.y < 0 || p.y > h) p.vy *= -1;
                const dm = Math.hypot(p.x - mouse.x, p.y - mouse.y);
                if (dm < 140) { p.x += (p.x - mouse.x) / dm; p.y += (p.y - mouse.y) / dm; }
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(${base},.7)`;
                ctx.fill();
            }
            for (let i = 0; i < pontos.length; i++) {
                for (let j = i + 1; j < pontos.length; j++) {
                    const a = pontos[i], b = pontos[j];
                    const d = Math.hypot(a.x - b.x, a.y - b.y);
                    if (d < 120) {
                        ctx.strokeStyle = `rgba(${base},${(1 - d / 120) * 0.25})`;
                        ctx.lineWidth = 1;
                        ctx.beginPath();
                        ctx.moveTo(a.x, a.y);
                        ctx.lineTo(b.x, b.y);
                        ctx.stroke();
                    }
                }
            }
            requestAnimationFrame(desenhar);
        };
        requestAnimationFrame(desenhar);
    };

    /* ---------------- máquina de escrever ---------------- */
    function iniciarTypewriter() {
        document.querySelectorAll("[data-typewriter]").forEach((el) => {
            const frases = el.dataset.typewriter.split("|");
            if (reduzMovimento) { el.textContent = frases[0]; return; }
            let f = 0, c = 0, apagando = false;
            const tick = () => {
                const frase = frases[f];
                c += apagando ? -1 : 1;
                el.textContent = frase.slice(0, c);
                let espera = apagando ? 28 : 55;
                if (!apagando && c === frase.length) { apagando = true; espera = 1800; }
                else if (apagando && c === 0) { apagando = false; f = (f + 1) % frases.length; espera = 300; }
                setTimeout(tick, espera);
            };
            tick();
        });
    }

    /* ---------------- brilho do cursor ---------------- */
    function iniciarCursorGlow() {
        const glow = document.querySelector("[data-fo-cursor-glow]");
        if (!glow || ehToque) return;
        let x = innerWidth / 2, y = innerHeight / 2, gx = x, gy = y;
        addEventListener("pointermove", (e) => { x = e.clientX; y = e.clientY; }, { passive: true });
        const seguir = () => {
            gx += (x - gx) * 0.12;
            gy += (y - gy) * 0.12;
            glow.style.transform = `translate(${gx}px, ${gy}px) translate(-50%, -50%)`;
            requestAnimationFrame(seguir);
        };
        seguir();
    }

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
        iniciarTema();
        iniciarReveal();
        iniciarSpotlight();
        iniciarTilt();
        iniciarMagnetico();
        iniciarRipple();
        iniciarTypewriter();
        iniciarCursorGlow();
        iniciarFormularios();
        document.querySelectorAll("canvas[data-fo-particulas]").forEach((c) => FO.particulas(c));
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
    else iniciar();
})();

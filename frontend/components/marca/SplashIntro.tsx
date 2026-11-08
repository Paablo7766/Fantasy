/**
 * Intro de marca al abrir la app. HTML + CSS puro (se pinta antes de que React
 * hidrate). Sale en cada carga y se repite al volver a la app tras >5 min en
 * segundo plano (en móvil la PWA se reanuda sin recargar).
 *
 * Misma voz visual que Inicio: negro puro, halo naranja que cae desde arriba,
 * Inter con tracking ajustado y un solo gesto por elemento.
 */
export const SPLASH_HEAD_SCRIPT = `(function(){var h=0;document.addEventListener("visibilitychange",function(){if(document.hidden){h=Date.now();return}if(h&&Date.now()-h>3e5){var el=document.querySelector(".splash");if(el){var c=el.cloneNode(true);el.replaceWith(c)}}})})();`;

export function SplashIntro() {
  return (
    <div className="splash" aria-hidden="true">
      <div className="splash__halo" />
      <div className="splash__grain" />
      <div className="splash__content">
        <div className="splash__mark">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo-mark-plain.svg" alt="" width={88} height={90} />
        </div>
        <div className="splash__type">
          <p className="splash__eyebrow">Panel del mánager</p>
          <p className="splash__name">
            <span className="splash__name-inner">LALIGA <b>Fantasy</b></span>
          </p>
        </div>
      </div>
      <span className="splash__line"><i /></span>
    </div>
  );
}

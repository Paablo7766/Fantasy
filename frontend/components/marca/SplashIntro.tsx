/**
 * Intro de marca al abrir la app. HTML + CSS puro (se pinta antes de que React
 * hidrate). Sale en cada carga y se repite al volver a la app tras >5 min en
 * segundo plano (en móvil la PWA se reanuda sin recargar).
 *
 * Mínima: negro, un resplandor tenue, logo y nombre. ~1,3 s en total.
 */
export const SPLASH_HEAD_SCRIPT = `(function(){var h=0;document.addEventListener("visibilitychange",function(){if(document.hidden){h=Date.now();return}if(h&&Date.now()-h>3e5){var el=document.querySelector(".splash");if(el){var c=el.cloneNode(true);el.replaceWith(c)}}})})();`;

export function SplashIntro() {
  return (
    <div className="splash" aria-hidden="true">
      <div className="splash__halo" />
      <div className="splash__content">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="splash__mark" src="/logo-mark-plain.svg" alt="" width={40} height={41} />
        <span className="splash__name">
          <span className="splash__word">LALIGA</span> <b className="splash__word splash__word--2">Fantasy</b>
        </span>
      </div>
    </div>
  );
}

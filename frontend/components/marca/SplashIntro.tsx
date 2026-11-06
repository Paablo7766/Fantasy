/**
 * Intro de marca al abrir la app. HTML + CSS puro (se pinta antes de que React
 * hidrate). Sale en cada carga y se repite al volver a la app tras >5 min en
 * segundo plano (en móvil la PWA se reanuda sin recargar).
 */
export const SPLASH_HEAD_SCRIPT = `(function(){var h=0;document.addEventListener("visibilitychange",function(){if(document.hidden){h=Date.now();return}if(h&&Date.now()-h>3e5){var el=document.querySelector(".splash");if(el){var c=el.cloneNode(true);el.replaceWith(c)}}})})();`;

export function SplashIntro() {
  return (
    <div className="splash" aria-hidden="true">
      <div className="splash__glow" />
      <div className="splash__stage">
        <span className="splash__ring" />
        <span className="splash__ring splash__ring--2" />
        <div className="splash__logo">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo-mark.svg" alt="" width={120} height={123} />
          <span className="splash__shine" />
        </div>
      </div>
      <p className="splash__word">
        {"LALIGA".split("").map((c, i) => (
          <span key={i} style={{ animationDelay: `${0.9 + i * 0.045}s` }}>{c}</span>
        ))}
        <span className="splash__word-gap" />
        {"FANTASY".split("").map((c, i) => (
          <span key={`f${i}`} className="splash__word-accent" style={{ animationDelay: `${1.2 + i * 0.045}s` }}>{c}</span>
        ))}
      </p>
      <span className="splash__bar"><i /></span>
    </div>
  );
}

/**
 * Intro de marca al abrir la app. Es HTML + CSS puro (se pinta antes de que
 * React hidrate) y solo sale una vez por sesión: el script del <head> marca
 * <html data-splash="off"> si ya se vio, y el CSS lo oculta al instante.
 */
export const SPLASH_HEAD_SCRIPT = `try{if(sessionStorage.getItem("splash-v1")){document.documentElement.dataset.splash="off"}else{sessionStorage.setItem("splash-v1","1")}}catch(e){}`;

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

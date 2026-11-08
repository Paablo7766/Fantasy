import { Fragment, type CSSProperties } from "react";

/**
 * Texto que aparece palabra a palabra, de borroso a nítido. Se vuelve a
 * revelar solo cuando cambia el texto (clave = texto), así una conclusión
 * nueva tras actualizar se nota sin animar nada más.
 */
export function BlurText({ text, delay = 0, step = 55 }: { text: string; delay?: number; step?: number }) {
  const words = text.split(/\s+/).filter(Boolean);
  return (
    <span key={text} className="blur-text">
      <span className="sr-only">{text}</span>
      {words.map((word, i) => (
        <Fragment key={i}>
          <span aria-hidden="true" className="blur-text__w" style={{ "--d": `${delay + i * step}ms` } as CSSProperties}>
            {word}
          </span>
          {i < words.length - 1 ? " " : null}
        </Fragment>
      ))}
    </span>
  );
}

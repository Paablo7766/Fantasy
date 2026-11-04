/**
 * Reglamento de esta liga. LaLiga Fantasy permite banquillo automático,
 * capitán (x2) y ficha de entrenador. Aquí los tres están apagados: solo
 * puntúan los 11 alineados, nadie dobla y un entrenador no se ficha.
 */
export const REGLAMENTO: {
  banquillo: boolean;
  capitan: boolean;
  entrenador: boolean;
} = {
  banquillo: false,
  capitan: false,
  entrenador: false,
};

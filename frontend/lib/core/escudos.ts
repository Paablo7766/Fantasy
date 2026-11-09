/** Escudos de los clubes: los que sirve LaLiga Fantasy en su CDN (``teambadge``). */
const CDN = "https://assets-fantasy.llt-services.com/teambadge";

/** [palabra que identifica al club en el nombre normalizado, escudo]. El orden importa: Alavés antes que Deportivo. */
const CLUBES: Array<[string, string]> = [
  ["alaves", "t173/color/t173_d-alaves.png"],
  ["deportivo", "t180/color/t180_rc-deportivo.png"],
  ["athletic", "t174/color/t174_athletic-club.png"],
  ["atletico", "t175/color/t175_atletico-de-madrid.png"],
  ["osasuna", "t450/color/t450_c-a-osasuna.png"],
  ["elche", "t954/color/t954_elche-c-f.png"],
  ["barcelona", "t178/color/t178_fc-barcelona.png"],
  ["getafe", "t1450/color/t1450_getafe-cf.png"],
  ["levante", "t855/color/t855_levante-ud.png"],
  ["malaga", "t182/color/t182_malaga-cf.png"],
  ["racing", "t189/color/t189_r-racing-club.png"],
  ["rayo", "t184/color/t184_rayo-vallecano.png"],
  ["celta", "t176/color/t176_rc-celta.png"],
  ["espanyol", "t177/color/t177_rcd-espanyol.png"],
  ["betis", "t185/color/t185_real-betis.png"],
  ["real madrid", "t186/color/t186_real-madrid.png"],
  ["real sociedad", "t188/color/t188_real-sociedad.png"],
  ["sevilla", "t179/color/t179_sevilla-fc.png"],
  ["valencia", "t191/color/t191_valencia-cf.png"],
  ["villarreal", "t449/color/t449_villarreal-cf.png"],
];

function normalizar(nombre: string): string {
  return nombre
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** URL del escudo del club, o ``null`` si el nombre no corresponde a ninguno de la liga. */
export function escudoDe(club: string | null | undefined): string | null {
  if (!club) return null;
  const nombre = normalizar(club);
  if (!nombre) return null;
  const hallado = CLUBES.find(([clave]) => nombre.includes(clave));
  return hallado ? `${CDN}/${hallado[1]}` : null;
}

import { eur, pct, playerName, points } from "@/lib/format";
import { marketAction } from "@/lib/marketAction";
import type { MarketDecision } from "@/lib/types";

const POSITION: Record<string, string> = {
  POR: "portero",
  DEF: "defensa",
  MED: "centrocampista",
  DEL: "delantero",
};

const MOTIVE: Record<string, string> = {
  flip: "Puede revalorizarse",
  puntos: "Buenos puntos por euro",
  hueco: "Cubre un hueco de tu once",
  calendario: "El calendario le favorece",
  mejora_xi: "Mejora tu once",
  no_mejora_xi: "No entra en tu once",
  snipe: "Espera al cierre",
  snipe_techo: "Entra en el cierre",
  fuentes_no_coinciden: "Las fuentes no cuadran",
  sobre_techo: "Por encima del tope",
  sin_caja: "No llega la caja",
  sobreprecio: "Está caro",
  senal_bajista: "El precio va a la baja",
  senal_debil: "La señal es floja",
  sin_motivo: "Sin motivo claro",
  matching_confidence: "Datos poco fiables",
  ya_en_plantilla: "Ya lo tienes",
  listing_propio: "Es tu propia venta",
  lesionado: "Está lesionado",
  sancionado: "Está sancionado",
  mercado_cerrado: "El mercado ya cerró",
  negative_cash: "Te dejaría sin caja",
  xi_invalido: "Rompe tu once",
  esperar_snipe: "Espera al cierre",
  lider_supera_ideal: "La puja ya supera el precio justo",
  suelo_sobre_ideal: "La salida ya es cara",
  veto: "No se puede fichar",
  caja_otros_mercados: "Guarda caja para otros mercados",
  caja_otras_pujas: "La caja ya está en otras pujas",
};

const MISSING: Record<string, string> = {
  ideal_bid: "No hay un precio justo calculado, así que no podemos decir si está barato.",
  max_bid: "No hay tope de puja. Sin ese techo no sabemos dónde parar.",
  expected_points: "No hay puntos esperados para esta jornada.",
  p_titular: "No sabemos qué probabilidad tiene de ser titular.",
  price_delta: "No hay variación de precio de hoy.",
  market_signal: "No hay señal de si el precio va a seguir subiendo o bajando. La recomendación no apuesta a eso.",
  matching_confidence: "El cruce con Analítica Fantasy no es fiable, así que esa fuente no cuenta como motivo para pujar.",
};

export type BidFact = { label: string; value: string; note: string };

export type BidStory = {
  glance: string;
  motive: string;
  headline: string;
  action: string;
  reasons: string[];
  theory: string;
  gaps: string[];
  facts: BidFact[];
};

function positionName(position: string | null | undefined): string {
  if (!position) return "esa posición";
  return POSITION[position] || position.toLowerCase();
}

export function motiveText(key: string | null | undefined): string {
  if (!key) return "Sin lectura";
  return MOTIVE[key] || key.replace(/_/g, " ");
}

function sourceName(source: string | null | undefined): string {
  if (source === "own") return "tu proyección";
  if (source === "af") return "Analítica Fantasy";
  if (source === "own+af") return "tu proyección y Analítica Fantasy";
  return "";
}

function signedPoints(value: number): string {
  return `${value > 0 ? "+" : ""}${points(value)}`;
}

function hasMotive(player: MarketDecision, key: string): boolean {
  return (player.motives || []).includes(key);
}

export function bidGlance(player: MarketDecision): string {
  const delta = player.points_delta;
  if (typeof delta === "number" && delta > 0) {
    const who = player.replaces?.name ? ` sobre ${player.replaces.name}` : " en tu once";
    return `${signedPoints(delta)} pts${who}`;
  }
  if (player.primary_motive === "hueco") return `Te falta un ${positionName(player.position)}`;
  if (player.primary_motive === "flip") return "El precio puede subir";
  if (player.primary_motive === "puntos") return "Devuelve puntos por lo que cuesta";
  if (player.primary_motive === "snipe" || player.bid_limit === "snipe_techo") {
    return player.snipe?.fire_local_clock ? `Entra a las ${player.snipe.fire_local_clock}` : "Espera al cierre";
  }
  if (player.bid_limit === "sobre_techo" || player.primary_motive === "sobreprecio") return "Ya pasa el tope de precio";
  if (player.bid_limit === "sin_caja" || player.primary_motive === "sin_caja") return "No te llega la caja";
  if (typeof player.p_titular === "number") return `Titular el ${pct(player.p_titular)}`;
  return motiveText(player.primary_motive);
}

export function bidCapLine(player: MarketDecision): string {
  if (player.bid_limit === "snipe_techo" || player.bid_limit === "snipe_liga") {
    return player.snipe?.fire_local_clock ? `en el cierre, ${player.snipe.fire_local_clock}` : "en el cierre";
  }
  if (typeof player.raise_to === "number") return `máximo ${eur(player.raise_to)}`;
  if (player.bid_limit === "sin_techo") return "sin tope contrastado";
  if (player.bid_limit === "sobre_techo" || player.bid_limit === "fuentes_no_coinciden") return "supera el tope";
  if (player.bid_limit === "sin_caja") return "no llega la caja";
  if (typeof player.value_ceiling === "number" && marketAction(player) !== "NO") return `tope ${eur(player.value_ceiling)}`;
  return "";
}

function priceNote(player: MarketDecision): string | null {
  const ceiling = typeof player.value_ceiling === "number" ? eur(player.value_ceiling) : null;
  const source = sourceName(player.value_ceiling_source);
  const ceilingText = ceiling ? (source ? `${ceiling} (${source})` : ceiling) : null;
  const action = marketAction(player);
  if (action === "NO") {
    return player.is_vetoed
      ? "El motor lo veta: no hay cifra de puja que ofrecer."
      : "Con este precio no hay margen: cada euro extra compra los mismos puntos a peor precio.";
  }
  if (player.bid_limit === "abrir" || player.bid_limit === "snipe_liga") {
    return ceilingText
      ? `Salida por debajo del tope de ${ceilingText}: el margen está en el precio, no en la prisa.`
      : "El precio de salida queda por debajo del precio justo.";
  }
  if (ceilingText && action === "PUJAR") {
    return `El tope para no pasarte es ${ceilingText}.`;
  }
  if (ceilingText) {
    return `Techo de referencia ${ceilingText}: por encima, la puja deja de compensar.`;
  }
  return null;
}

function rivalLine(player: MarketDecision): string | null {
  const bids = player.rival_bids || [];
  if (typeof player.leading_bid === "number") {
    const leader = bids.find((bid) => bid.amount === player.leading_bid);
    const who = leader?.manager_name ? ` (${leader.manager_name})` : "";
    const extra = bids.length > 1 ? ` Hay ${bids.length} pujas.` : "";
    return `Ahora va ganando ${eur(player.leading_bid)}${who}.${extra}`;
  }
  if (typeof player.sale_price === "number" || typeof player.bid_eur === "number") {
    return `Nadie ha pujado. La salida es ${eur(player.sale_price ?? player.bid_eur)}.`;
  }
  return null;
}

function overbidLine(player: MarketDecision): string | null {
  const risk = player.bid_plan?.overbid;
  if (!risk?.status || marketAction(player) === "NO") return null;
  const count = risk.count;
  if (risk.status === "high") {
    const n = typeof count === "number" && count > 0 ? `${count} ` : "";
    return `${n}rivales tienen dinero y un hueco de ${positionName(player.position)}. Te pueden pasar por encima.`;
  }
  if (risk.status === "low") {
    return `Ningún rival con caja conocida necesita un ${positionName(player.position)}. Es menos probable que te superen.`;
  }
  if (risk.reason === "caja_desconocida") {
    return "Falta la caja de algún rival, así que no sabemos si te pueden superar.";
  }
  if (risk.reason === "sin_rivales") {
    return "No hay datos de rivales para saber si alguien puede pasar por encima.";
  }
  if (risk.reason === "sin_ideal") {
    return "Sin un precio justo no se puede contar quién tiene dinero para superarte.";
  }
  return null;
}

function leagueBlocked(player: MarketDecision): string {
  if (!player.league_bid_blocked || typeof player.league_bid !== "number") return "";
  return ` Para cubrir la guerra de la liga harían falta ${eur(player.league_bid)}, y eso pasa tu tope.`;
}

function leagueHistoryLine(player: MarketDecision): string | null {
  if (marketAction(player) === "NO") return null;
  const wars = player.league_war_count ?? 0;
  const median = player.league_median_premium;
  const priced = player.league_priced_count ?? 0;
  const buys = player.league_buy_count ?? 0;
  if (typeof player.league_bid === "number" && !player.league_bid_blocked) {
    const typical =
      typeof median === "number" ? ` En esta liga, cuando hay guerra, se paga un ${pct(median)} por encima del valor de ese día.` : "";
    return `La cifra no es un euro más que el líder: para ganar aquí suele hacer falta ${eur(player.league_bid)}.${typical}`;
  }
  if (typeof player.league_bid === "number" && player.league_bid_blocked) {
    return typeof median === "number"
      ? `La sobrepuja típica de esta liga es un ${pct(median)} sobre el valor del día. No se recomienda pagar esa guerra: pasa el tope.`
      : null;
  }
  if (wars < 3 && priced > 0) {
    return `El historial tiene ${priced} compras con el valor de ese día. Hacen falta 3 guerras de rivales que puedan pagar este precio para fijar cuánto sobrepujar.`;
  }
  if (wars < 3 && buys > 0) {
    return `Hay ${buys} compras en el historial de la liga, pero no está guardado el valor de esos días, así que no se puede medir la sobrepuja típica.`;
  }
  if (wars < 3) {
    return "Todavía no hay historial de compras de la liga para saber cuánto se suele sobrepujar.";
  }
  if (typeof median === "number") {
    return `En esta liga la sobrepuja típica es un ${pct(median)} sobre el valor del día, pero para este precio no hay 3 rivales que puedan pagarla.`;
  }
  return null;
}

function actionText(player: MarketDecision): string {
  const action = marketAction(player);
  const bid = player.suggested_bid;
  const ceiling = typeof player.value_ceiling === "number" ? eur(player.value_ceiling) : null;
  const clock = player.snipe?.fire_local_clock;
  const cap = typeof player.raise_to === "number" ? ` Si te superan, para en ${eur(player.raise_to)}.` : "";

  if (action === "NO" || (typeof bid !== "number" && player.bid_limit === "no")) {
    if (player.action_reason) return `No pongas dinero aquí. ${player.action_reason}`;
    return `No pongas dinero aquí. ${motiveText(player.primary_motive)}.`;
  }
  if (player.bid_limit === "sobre_techo") {
    return ceiling
      ? `La puja para ir primero ya supera el tope de ${ceiling}. Perseguirla es pagar de más por los mismos puntos.`
      : "La puja para ir primero ya supera el tope. No la persigas.";
  }
  if (player.bid_limit === "fuentes_no_coinciden") {
    return "Para ponerte primero tendrías que saltarte la fuente más baja. Como no coinciden, no subas.";
  }
  if (player.bid_limit === "sin_caja") {
    return "Tu caja no llega a una oferta que te deje primero.";
  }
  if (player.primary_motive === "caja_otros_mercados") {
    const price = typeof bid === "number" ? ` Costaría ${eur(bid)}.` : "";
    return `No gastes aquí hoy. Quedan más mercados antes de la jornada y este precio se come el presupuesto del día.${price} Guarda la caja.`;
  }
  if (player.primary_motive === "caja_otras_pujas") {
    const price = typeof bid === "number" ? ` Costaría ${eur(bid)}.` : "";
    return `No sumes esta puja. La caja de hoy ya está en fichajes mejores.${price}`;
  }
  if (player.bid_limit === "snipe_techo" && typeof bid === "number") {
    const when = clock ? `A las ${clock}` : "En el cierre";
    return `${when} ofrece ${eur(bid)}, el tope. No entres antes: lo verían y sumarían 1 €.`;
  }
  if (player.bid_limit === "snipe_liga" && typeof bid === "number") {
    const when = clock ? `A las ${clock}` : "En el cierre";
    const blocked = leagueBlocked(player);
    return `${when} ofrece ${eur(bid)}. Es lo que ha hecho falta en esta liga para ganar cuando alguien puja de verdad, no un euro más que el líder.${blocked}`;
  }
  if (player.bid_limit === "abrir" && typeof bid === "number") {
    const league =
      typeof player.league_bid === "number" && player.league_bid === bid && !player.league_bid_blocked
        ? " Es la mediana de sobrepuja de esta liga, no el precio justo a secas."
        : "";
    return `Ofrece ${eur(bid)} ahora. Nadie va por delante y, si empatan tu cifra, gana quien pujó antes.${league}${cap}${leagueBlocked(player)}`;
  }
  if (player.bid_limit === "ir_primero" && typeof bid === "number") {
    const league =
      typeof player.league_bid === "number" && player.league_bid === bid && !player.league_bid_blocked
        ? " Cubre la sobrepuja que se ha visto en esta liga."
        : "";
    return `Puja ${eur(bid)} para ponerte primero.${league}${cap}`;
  }
  if (player.bid_limit === "sin_techo" && typeof bid === "number") {
    return `Puedes ofrecer ${eur(bid)} para ir primero, pero no hay un tope contrastado. No subas de esa cifra.`;
  }
  if (typeof bid === "number") return `La cifra orientativa es ${eur(bid)}.${cap}`;
  if (action === "ESPERAR") return `${motiveText(player.primary_motive)}. Guarda la caja.`;
  return "No hay una cifra recomendada.";
}

function headline(player: MarketDecision): string {
  const motive = player.primary_motive;
  const action = marketAction(player);
  if (action === "PUJAR" && motive === "mejora_xi") {
    return "Puja: entra en tu once y el precio cabe bajo el tope.";
  }
  if (action === "PUJAR" && motive === "hueco") {
    return "Puja: te falta gente en esa posición y el precio es asumible.";
  }
  if (action === "PUJAR" && motive === "flip") {
    return "Puja: el precio tiene recorrido y no pagas de más.";
  }
  if (action === "PUJAR" && motive === "puntos") {
    return "Puja: devuelve puntos por cada euro, y el precio no se dispara.";
  }
  if (action === "PUJAR") return "Puja: hay un motivo de puntos o de precio, y la cifra es asumible.";
  if (action === "ESPERAR" && (motive === "snipe" || player.bid_limit === "snipe_techo")) {
    return "Quiérelo, pero no enseñes la puja hasta el cierre.";
  }
  if (action === "ESPERAR" && (motive === "sobreprecio" || motive === "sobre_techo" || motive === "lider_supera_ideal")) {
    return "El jugador encaja, pero ya está demasiado caro.";
  }
  if (action === "ESPERAR" && motive === "caja_otros_mercados") {
    return "Encaja, pero hoy no: quedan más mercados antes de la jornada y la caja de hoy ya está asignada.";
  }
  if (action === "ESPERAR" && motive === "caja_otras_pujas") {
    return "Encaja, pero la caja de este mercado ya está en pujas mejores.";
  }
  if (action === "ESPERAR") return "Hay una pista, no un motivo suficiente para gastar caja ahora.";
  if (action === "NO" && player.action_reason) return player.action_reason;
  if (motive === "ya_en_plantilla") return "Ya está en tu plantilla.";
  if (motive === "lesionado" || motive === "sancionado") return "No va a jugar. El dinero no se convierte en puntos.";
  if (motive === "senal_bajista") return "El precio va a la baja y no te mejora el once.";
  return motiveText(motive);
}

function theoryText(player: MarketDecision): string {
  const name = playerName(player);
  const action = marketAction(player);
  const chunks: string[] = [];
  const delta = player.points_delta;
  const replaces = player.replaces?.name;
  const ceiling = typeof player.value_ceiling === "number" ? eur(player.value_ceiling) : null;
  const source = sourceName(player.value_ceiling_source);
  const bid = typeof player.suggested_bid === "number" ? eur(player.suggested_bid) : null;

  if (typeof delta === "number" && delta > 0 && replaces) {
    chunks.push(
      `Una puja solo merece la pena si suma puntos a tu once. ${name} entra por delante de ${replaces} y aporta ${signedPoints(delta)} puntos esperados: el dinero se convierte en alineación, no en un nombre en el banquillo.`,
    );
  } else if (hasMotive(player, "hueco_xi") || hasMotive(player, "hueco_posicion") || player.primary_motive === "hueco") {
    chunks.push(
      `Sin un ${positionName(player.position)} el once queda cojo. Cubrir ese hueco vale más que fichar un nombre caro en una posición que ya tienes cubierta.`,
    );
  } else if (player.primary_motive === "flip" || hasMotive(player, "aceleracion") || hasMotive(player, "own_predicted_up")) {
    chunks.push(
      `Aquí el motivo no es el once de esta jornada, sino el precio. La tendencia dice que el valor puede subir, y vender más caro es caja para la siguiente puja.`,
    );
  } else if (player.primary_motive === "puntos" || hasMotive(player, "puntos_jornada")) {
    chunks.push(
      `Con la caja limitada gana quien compra puntos baratos. ${name} devuelve puntos por euro, así que el fichaje se justifica por rendimiento, no por el nombre.`,
    );
  } else if (action === "NO") {
    chunks.push(
      `Sin mejora de once, sin hueco y sin un precio que vaya a subir, gastar aquí te deja más pobre para la puja que sí merezca la pena.`,
    );
  } else if (action === "ESPERAR") {
    chunks.push(
      `Hay algo a favor, pero no lo bastante como para inmovilizar la caja ahora. Esperar conserva el dinero por si sale una puja mejor.`,
    );
  }

  if (ceiling && bid && action === "PUJAR") {
    chunks.push(
      `El tope${source ? ` de ${source}` : ""} es ${ceiling}: lo máximo que aceptamos pagar. ${bid} queda por debajo, así que no estás persiguiendo la puja por orgullo.`,
    );
  } else if (player.bid_limit === "sobre_techo" || player.bid_limit === "fuentes_no_coinciden") {
    chunks.push("Pasado el tope, cada euro extra compra los mismos puntos a peor precio. Por eso la orden es no seguir la puja.");
  } else if (player.bid_limit === "sin_techo") {
    chunks.push(
      "Sin tope de Analítica Fantasy ni de la proyección propia no hay un «vale X». La única cifra segura es la justa para ir primero, y ahí hay que parar.",
    );
  }

  const afPts = player.af_expected_points;
  const ownPts = player.own_expected_points;
  if (typeof ownPts === "number" && typeof afPts === "number" && Math.abs(afPts - ownPts) >= 0.8) {
    chunks.push(
      `Analítica Fantasy le pone ${points(afPts)} puntos esperados; tu proyección de jornada es ${points(ownPts)}. AF no descuenta igual la titularidad: esa cifra alta no es lo que suma al once si no sale.`,
    );
  } else if (player.expected_points_source === "own" && typeof ownPts === "number") {
    chunks.push(
      `Tu proyección de jornada es ${points(ownPts)} puntos: ya incluye que a veces no juega. No hay que volver a bajarla por la titularidad.`,
    );
  } else if (
    typeof player.jornada_ev === "number" &&
    typeof player.expected_points === "number" &&
    typeof player.p_titular === "number" &&
    player.expected_points_source !== "own"
  ) {
    chunks.push(
      `Los ${points(player.expected_points)} puntos de Analítica Fantasy (o OPTA) solo cuentan si juega. El valor de la jornada es ${points(player.jornada_ev)}: esa cifra por un ${pct(player.p_titular)} de titular.`,
    );
  }

  if (player.bid_limit === "abrir") {
    chunks.push("En un empate gana quien pujó antes. Si nadie va por delante, esperar al último segundo regala ese empate.");
  } else if (player.bid_limit === "snipe_techo") {
    chunks.push(
      "Con alguien ya por delante, pujar pronto solo avisa. En el cierre se entra al tope: si el otro suma 1 € después, se queda fuera de tiempo.",
    );
  }

  if ((player.missing_inputs || []).includes("market_signal") && action !== "NO") {
    chunks.push(
      "Falta la señal de si el precio seguirá subiendo o bajando. Esta lectura no apuesta a eso: se apoya en el once, la titularidad y el tope.",
    );
  }

  return chunks.join(" ");
}

function facts(player: MarketDecision): BidFact[] {
  const rows: BidFact[] = [];
  const pts = player.own_expected_points ?? player.af_expected_points ?? player.expected_points;
  if (typeof player.optimal_bid_eur === "number") {
    rows.push({
      label: "Puja óptima v2",
      value: eur(player.optimal_bid_eur),
      note:
        player.bid_intent === "STRUCTURAL"
          ? "Compra estructural (once / hueco)"
          : player.bid_intent === "FLIP"
            ? "Especulación por revalorización"
            : "Maximiza (valor − puja) × P(ganar)",
    });
  }
  if (typeof player.win_probability === "number") {
    const pctWin =
      player.win_probability <= 1
        ? `${Math.round(player.win_probability * 100)}%`
        : `${Math.round(player.win_probability)}%`;
    rows.push({ label: "Prob. victoria", value: pctWin, note: "Modelo de rivales y techos de caja" });
  }
  if (typeof player.intrinsic_valuation_eur === "number") {
    rows.push({
      label: "Valor intrínseco",
      value: eur(player.intrinsic_valuation_eur),
      note: "V_val según flip o premium estructural",
    });
  }
  if (typeof player.expected_surplus_eur === "number") {
    rows.push({
      label: "Superávit esperado",
      value: eur(player.expected_surplus_eur),
      note: "(V_val − puja) × P(ganar)",
    });
  }
  if ((player.rival_knockout_targets?.length ?? 0) > 0) {
    rows.push({
      label: "Knock-out",
      value: player.rival_knockout_targets!.join(", "),
      note: "Rivales cuyo techo de caja puedes superar con poco extra",
    });
  }
  if (typeof player.suggested_bid === "number") {
    rows.push({
      label: "Qué ofreces",
      value: eur(player.suggested_bid),
      note: player.bid_limit === "snipe_techo" || player.bid_limit === "snipe_liga" ? "En el cierre, no ahora" : "La cifra para llevarte la puja",
    });
  }
  if (typeof player.league_bid === "number") {
    rows.push({
      label: "Puja de liga",
      value: eur(player.league_bid),
      note: player.league_bid_blocked
        ? "La sobrepuja típica de la liga pasa tu tope"
        : "Mediana de sobrepujas del historial, rivales que pueden pagar",
    });
  }
  if (typeof player.league_median_premium === "number") {
    rows.push({
      label: "Sobrepuja típica",
      value: pct(player.league_median_premium),
      note: `${player.league_war_count ?? 0} guerras con valor de ese día`,
    });
  }
  if (typeof player.raise_to === "number") {
    rows.push({ label: "Dónde paras", value: eur(player.raise_to), note: "Si te superan, no sigas" });
  } else if (typeof player.value_ceiling === "number") {
    rows.push({
      label: "Tope",
      value: eur(player.value_ceiling),
      note: sourceName(player.value_ceiling_source) || "Lo máximo que vale según las fuentes",
    });
  }
  if (typeof player.leading_bid === "number") {
    rows.push({ label: "Va ganando", value: eur(player.leading_bid), note: "La puja más alta ahora mismo" });
  } else if (typeof (player.sale_price ?? player.bid_eur) === "number") {
    rows.push({ label: "Precio de salida", value: eur(player.sale_price ?? player.bid_eur), note: "Todavía no hay puja" });
  }
  if (typeof player.own_expected_points === "number") {
    rows.push({
      label: "Tu proyección",
      value: `${points(player.own_expected_points)} pts`,
      note: "Valor de jornada (ya descuenta titularidad y minutos)",
    });
  } else if (typeof pts === "number") {
    rows.push({ label: "Si juega", value: `${points(pts)} pts`, note: "Puntos esperados del partido" });
  }
  if (typeof player.af_expected_points === "number" && player.expected_points_source !== "af") {
    rows.push({
      label: "Analítica Fantasy",
      value: `${points(player.af_expected_points)} pts`,
      note: "Oráculo AF: no es el valor de jornada y no decide la puja",
    });
  }
  if (typeof player.p_titular === "number") {
    rows.push({ label: "Titular", value: pct(player.p_titular), note: "Probabilidad de salir de inicio" });
  }
  if (typeof player.jornada_ev === "number") {
    rows.push({
      label: "Valor de la jornada",
      value: `${points(player.jornada_ev)} pts`,
      note:
        player.expected_points_source === "own"
          ? "Misma cifra que tu proyección: no se vuelve a multiplicar por titular"
          : "Puntos esperados × probabilidad de titular",
    });
  }
  if (typeof player.points_delta === "number") {
    rows.push({
      label: "Frente a tu once",
      value: `${signedPoints(player.points_delta)} pts`,
      note: player.replaces?.name ? `Respecto a ${player.replaces.name}` : "Respecto al más flojo de esa posición",
    });
  }
  if (typeof player.cash_after_eur === "number" && marketAction(player) !== "NO") {
    const afterNote =
      player.primary_motive === "caja_otros_mercados" || player.primary_motive === "caja_otras_pujas"
        ? "Caja que queda si pujas solo las que caben hoy"
        : "Lo que quedaría tras las pujas de hoy, hasta esta";
    rows.push({ label: "Caja después", value: eur(player.cash_after_eur), note: afterNote });
  }
  return rows;
}

export function bidStory(player: MarketDecision): BidStory {
  const reasons: string[] = [];
  const delta = player.points_delta;
  if (typeof delta === "number" && delta > 0) {
    reasons.push(
      player.replaces?.name
        ? `Mejora tu once: entra por delante de ${player.replaces.name} y suma ${signedPoints(delta)} puntos esperados.`
        : `Mejora tu once en ${signedPoints(delta)} puntos esperados.`,
    );
  } else if (typeof delta === "number" && delta <= 0 && player.replaces?.name) {
    reasons.push(
      `No mejora tu once. ${player.replaces.name} ya cubre esa posición y este jugador queda ${signedPoints(delta)}.`,
    );
  } else if (player.primary_motive === "hueco") {
    reasons.push(`Te falta un ${positionName(player.position)}. El fichaje rellena el once, no solo el banquillo.`);
  }

  const price = priceNote(player);
  if (price) reasons.push(price);
  const rival = rivalLine(player);
  if (rival) reasons.push(rival);

  const pts = player.own_expected_points ?? player.af_expected_points ?? player.expected_points;
  if (typeof player.own_expected_points === "number" && typeof player.p_titular === "number") {
    const af =
      typeof player.af_expected_points === "number"
        ? ` Analítica Fantasy marca ${points(player.af_expected_points)} si juega.`
        : "";
    reasons.push(
      `Tu proyección de jornada es ${points(player.own_expected_points)} pts con un ${pct(player.p_titular)} de titular.${af}`,
    );
  } else if (typeof pts === "number" && typeof player.p_titular === "number") {
    const ev =
      typeof player.jornada_ev === "number"
        ? ` El valor de la jornada, descontando que a veces no juega, es ${points(player.jornada_ev)}.`
        : "";
    reasons.push(`Si juega se le esperan ${points(pts)} puntos y es titular el ${pct(player.p_titular)}.${ev}`);
  } else if (typeof player.p_titular === "number") {
    reasons.push(`Sale de inicio el ${pct(player.p_titular)} de las veces.`);
  }

  const fixture = player.fixture;
  if (fixture?.opponent) {
    const home = fixture.is_home === true ? "En casa" : fixture.is_home === false ? "Fuera" : "Juega";
    const hard =
      fixture.difficulty === "dificil" || fixture.difficulty === "muy_dificil"
        ? ", un partido duro"
        : fixture.difficulty === "facil" || fixture.difficulty === "muy_facil"
          ? ", un partido asequible"
          : "";
    reasons.push(`${home} contra ${fixture.opponent}${hard}.`);
  }

  const crowd = overbidLine(player);
  if (crowd && marketAction(player) !== "NO") reasons.push(crowd);
  const history = leagueHistoryLine(player);
  if (history) reasons.push(history);

  const injury = player.af_injury?.info || player.af_injury?.report;
  if (player.primary_motive === "lesionado" && injury) reasons.push(String(injury));
  const ban = player.af_suspension?.info || player.af_suspension?.report;
  if (player.primary_motive === "sancionado" && ban) reasons.push(String(ban));

  const gaps = (player.missing_inputs || [])
    .map((key) => MISSING[key])
    .filter((line): line is string => Boolean(line));

  return {
    glance: bidGlance(player),
    motive: motiveText(player.primary_motive),
    headline: headline(player),
    action: actionText(player),
    reasons,
    theory: theoryText(player),
    gaps,
    facts: facts(player),
  };
}

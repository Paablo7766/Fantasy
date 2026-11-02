/**
 * Lo máximo que puedes pujar hoy: caja más el endeudamiento permitido, que es
 * el 20 % del valor del equipo y solo vale para pujas. ``null`` si falta la caja.
 */
export const DEBT_SHARE = 0.2;

export function bidBudget(cash: number | null | undefined, squadValue: number | null | undefined): number | null {
  if (typeof cash !== "number" || Number.isNaN(cash)) return null;
  const debt = typeof squadValue === "number" && squadValue > 0 ? squadValue * DEBT_SHARE : 0;
  return cash + debt;
}

/** Un fichaje que no cabe en el presupuesto de puja. Sin presupuesto no se marca nada. */
export function beyondBudget(price: number | null | undefined, budget: number | null): boolean {
  return budget !== null && typeof price === "number" && price > budget;
}

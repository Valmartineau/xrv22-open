export type StyletTick = {
  x: number | null; y: number | null; p: number; etat: string;
};
export type Pt = { x: number; y: number; p: number };
export type Stroke = Pt[];

// Ajoute un tick : en contact (p>0, coords présentes) → prolonge le dernier
// stroke (en démarre un si le précédent est clos) ; sinon → clôt le trait courant.
export function ajouteTick(strokes: Stroke[], t: StyletTick): Stroke[] {
  const enContact = t.p > 0 && t.x !== null && t.y !== null;
  if (!enContact) {
    // marque une rupture : si le dernier stroke est non vide, on le laisse clos
    if (strokes.length && strokes[strokes.length - 1].length === 0) return strokes;
    return strokes.length && strokes[strokes.length - 1].length > 0
      ? [...strokes, []]
      : strokes;
  }
  const pt: Pt = { x: t.x as number, y: t.y as number, p: t.p };
  if (!strokes.length) return [[pt]];
  const last = strokes[strokes.length - 1];
  const next = strokes.slice(0, -1);
  return [...next, [...last, pt]];
}

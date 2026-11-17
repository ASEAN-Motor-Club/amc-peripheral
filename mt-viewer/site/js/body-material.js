export function isBodyMaterialSlot(slot, definition = {}) {
  return /^(Body|Palette|Shell|Mat_PolygonCity_Texture)/i.test(slot || "")
    || /M_Body|Body_|M_Palette/i.test(definition.materialName || "");
}

export function selectedBodyVariant(variants, requestedIndex) {
  if (!Number.isInteger(requestedIndex) || requestedIndex < 0) return null;
  return (variants || []).find((variant, position) => (variant.index ?? position) === requestedIndex) || null;
}

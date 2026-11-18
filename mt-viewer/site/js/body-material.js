export function isBodyMaterialSlot(slot, definition = {}) {
  return /^(Body|Palette|Shell|Mat_PolygonCity_Texture)/i.test(slot || "")
    || /M_Body|Body_|M_Palette/i.test(definition.materialName || "");
}

export function selectedBodyVariant(variants, requestedIndex) {
  if (!Number.isInteger(requestedIndex) || requestedIndex < 0) return null;
  return (variants || []).find((variant, position) => (variant.index ?? position) === requestedIndex) || null;
}

function baseMaterialName(value) {
  return (String(value || "").split(/[\/.]/).filter(Boolean).pop() || "").toLowerCase();
}

// A livery material must only replace slots that actually use that material.
// Nuke's body variant is M_Body, but its wheels/interior are the Palette slot;
// replacing every Palette slot with M_Body clears their textures (grey parts).
export function liverySlotMatches(definition = {}, variant = null) {
  const wanted = baseMaterialName(variant?.materialName || variant?.material);
  const actual = baseMaterialName(definition.materialName || definition.material);
  return !wanted || !actual || wanted === actual;
}

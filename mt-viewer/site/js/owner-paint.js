function exactColor(colors, key) {
  if (!key) return undefined;
  if (Object.hasOwn(colors, key)) return colors[key];
  const hit = Object.keys(colors).find(k => k.toLowerCase() === key.toLowerCase());
  return hit ? colors[hit] : undefined;
}

export function replacedAiBodySlots(bodyMaterials, selectedIndex) {
  if (selectedIndex == null) return [];
  return (bodyMaterials || []).filter(m => m.ai && m.index !== selectedIndex).map(m => m.name);
}

export function ownerColorForSlot(slot, colors, colourKeys, extraPaintSlots) {
  const direct = exactColor(colors, slot);
  if (direct) return direct;
  const index = extraPaintSlots[slot];
  if (index != null) {
    const inherited = exactColor(colors, colourKeys[index]);
    if (inherited) return inherited;
  }
  return exactColor(colors, slot.replace(/_\d+$/, ""))
      ?? exactColor(colors, slot.replace(/(_\d+)$/, "_01"));
}

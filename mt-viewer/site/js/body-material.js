export function selectedBodyVariant(variants, requestedIndex) {
  if (!Number.isInteger(requestedIndex) || requestedIndex < 0) return null;
  return (variants || []).find((variant, position) => (variant.index ?? position) === requestedIndex) || null;
}

export interface ReasoningRawEventEntry {
  itemSummary: string | null;
  raw: Record<string, unknown>;
}

export function contentText(content: unknown): string {
  if (typeof content === "string") return content.trim();
  if (!Array.isArray(content)) return "";
  return content
    .map((entry) => {
      if (typeof entry === "string") return entry;
      if (!entry || typeof entry !== "object") return "";
      if ((entry as { type?: unknown }).type === "text") {
        const text = (entry as { text?: unknown }).text;
        return typeof text === "string" ? text : "";
      }
      if ((entry as { type?: unknown }).type === "thinking") {
        const thinking = (entry as { thinking?: unknown }).thinking;
        return typeof thinking === "string" ? thinking : "";
      }
      return "";
    })
    .filter(Boolean)
    .join("\n")
    .trim();
}

export function assistantMetaEventText(event: ReasoningRawEventEntry): string | null {
  const method = typeof event.raw.method === "string" ? event.raw.method : "";
  if (
    method === "item/reasoning/summaryTextDelta"
    || method === "item/reasoning/textDelta"
  ) {
    return null;
  }

  const params =
    event.raw.params && typeof event.raw.params === "object"
      ? (event.raw.params as { item?: unknown })
      : null;
  const completedItem =
    params?.item && typeof params.item === "object"
      ? (params.item as { summary?: unknown; content?: unknown; text?: unknown })
      : null;

  const body =
    contentText(
      event.raw.message && typeof event.raw.message === "object"
        ? (event.raw.message as { content?: unknown }).content
        : null
    ) ||
    contentText(completedItem?.summary) ||
    contentText(completedItem?.content) ||
    (typeof completedItem?.text === "string" ? completedItem.text.trim() : "") ||
    (typeof event.raw.text === "string" ? event.raw.text.trim() : "");

  return body || null;
}

export function assistantMetaDeltaText(event: ReasoningRawEventEntry): string | null {
  const method = typeof event.raw.method === "string" ? event.raw.method : "";
  if (
    method !== "item/reasoning/summaryTextDelta"
    && method !== "item/reasoning/textDelta"
  ) {
    return null;
  }
  return typeof event.raw.params === "object"
    && event.raw.params
    && typeof (event.raw.params as { delta?: unknown }).delta === "string"
    ? ((event.raw.params as { delta: string }).delta || null)
    : null;
}

export function assistantMetaItemId(event: ReasoningRawEventEntry): string | null {
  if (typeof event.raw.itemId === "string" && event.raw.itemId.trim()) {
    return event.raw.itemId;
  }
  if (
    typeof event.raw.params === "object"
    && event.raw.params
    && typeof (event.raw.params as { itemId?: unknown }).itemId === "string"
    && (event.raw.params as { itemId: string }).itemId.trim()
  ) {
    return (event.raw.params as { itemId: string }).itemId;
  }
  if (
    typeof event.raw.params === "object"
    && event.raw.params
    && typeof (event.raw.params as { item?: unknown }).item === "object"
    && (event.raw.params as { item: { id?: unknown } }).item
    && typeof (event.raw.params as { item: { id?: unknown } }).item.id === "string"
    && (event.raw.params as { item: { id: string } }).item.id.trim()
  ) {
    return (event.raw.params as { item: { id: string } }).item.id;
  }
  return null;
}

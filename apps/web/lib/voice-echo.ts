// Whether a microphone transcript is the assistant hearing its own voice from the speakers.
//
// The check compares what was heard with what the assistant actually said, never with a list of
// words. A keyword list drops real questions: a visitor who addresses the assistant by name, or
// asks what the product can do, uses words the assistant also says, and was silently ignored.

const MIN_ECHO_WORDS = 4;
const ECHO_OVERLAP = 0.8;

export function isEchoOfAgent(transcript: string, recentReplies: readonly string[]): boolean {
  const heard = words(transcript);
  // Short phrases are too common to attribute to the assistant; a visitor may well repeat three words.
  if (heard.length < MIN_ECHO_WORDS) return false;
  const phrase = ` ${heard.join(" ")} `;
  return recentReplies.some((reply) => {
    const said = words(reply);
    if (said.length === 0) return false;
    if (` ${said.join(" ")} `.includes(phrase)) return true;
    // Recognisers drop and mishear words, so a near-complete overlap also counts.
    const vocabulary = new Set(said);
    const shared = heard.filter((word) => vocabulary.has(word)).length;
    return shared / heard.length >= ECHO_OVERLAP;
  });
}

function words(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[‘’]/g, "'")
    .replace(/[^a-z0-9' ]+/g, " ")
    .split(/\s+/)
    .filter(Boolean);
}

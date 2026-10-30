/** The steps of a call, in the order it goes through them (see backend call_health). */
export const STAGES: Record<string, { label: string; hint: string }> = {
  connect: { label: "Connect", hint: "No answer, an error, or the rep said nothing" },
  routing: { label: "Routing", hint: "The rep spoke but no tool ran: stuck in the opening" },
  collecting: { label: "Collecting", hint: "Ended before the read-back" },
  confirming: { label: "Confirming", hint: "Read back, but the rep never said yes" },
  briefing: { label: "Briefing", hint: "No doctor found for the briefing" },
  false_close: { label: "False close", hint: "Saathi said recorded, but nothing was confirmed" },
  tool_error: { label: "Tool error", hint: "A tool call failed on the backend" },
  loop: { label: "Loop", hint: "The agent kept checking with nothing new from the rep" },
  saving: { label: "Saving", hint: "Confirmed, but the visit could not be built" },
};

export const OUTCOMES: Record<string, { label: string; tone: "good" | "brand" | "default" | "bad" }> = {
  recorded: { label: "Recorded", tone: "good" },
  briefing: { label: "Briefing", tone: "brand" },
  stopped: { label: "Rep stopped", tone: "default" },
  wrong_number: { label: "Wrong number", tone: "default" },
  failed: { label: "Failed", tone: "bad" },
};

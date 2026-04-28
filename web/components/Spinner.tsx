"use client";

// Shared 14×14 spinner used by SimulationSummary and TicketBuilder. The
// rotation keyframes are inlined (rather than relying on globals.css) so
// the component is drop-in for any consumer.
export function Spinner() {
  return (
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: 14,
        height: 14,
        border: "2px solid var(--border)",
        borderTopColor: "var(--accent)",
        borderRadius: "50%",
        animation: "derby-spin 0.8s linear infinite",
      }}
    >
      <style>{`@keyframes derby-spin{to{transform:rotate(360deg)}}`}</style>
    </span>
  );
}

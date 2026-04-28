"use client";

import { useEffect, useRef, useState } from "react";

interface OddsOverrideProps {
  horseName: string;
  current?: string | null;
  morningLine?: string | null;
  initial?: string | null;
  onSubmit: (value: string | null) => void;
  onClose: () => void;
}

// Simple modal input. Accepts fractional ("5/2", "8-1") or decimal ("3.5")
// strings — validation happens server-side. Empty input clears the override.
export function OddsOverride({
  horseName,
  current,
  morningLine,
  initial,
  onSubmit,
  onClose,
}: OddsOverrideProps) {
  const [value, setValue] = useState(initial ?? current ?? "");
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function commit(raw: string) {
    const trimmed = raw.trim();
    onSubmit(trimmed === "" ? null : trimmed);
    onClose();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Override odds for ${horseName}`}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(20, 20, 30, 0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1.5rem",
        zIndex: 50,
      }}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          commit(value);
        }}
        style={{
          width: "min(360px, 100%)",
          background: "var(--surface)",
          borderRadius: 14,
          padding: "1rem",
          boxShadow: "0 10px 40px rgba(0,0,0,0.25)",
          display: "flex",
          flexDirection: "column",
          gap: "0.75rem",
        }}
      >
        <div>
          <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Manual odds override
          </div>
          <div style={{ fontSize: "1.1rem", fontWeight: 600 }}>{horseName}</div>
          <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            ML {morningLine ?? "—"} · Current {current ?? "—"}
          </div>
        </div>

        <input
          ref={ref}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="e.g. 5/2"
          className="tap-target"
          style={{
            padding: "0.5rem 0.75rem",
            borderRadius: 10,
            border: "1px solid var(--border)",
            fontSize: "1.1rem",
            fontVariantNumeric: "tabular-nums",
          }}
        />

        <div
          style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}
        >
          <button
            type="button"
            className="tap-target"
            onClick={() => commit("")}
            style={{
              padding: "0.5rem 1rem",
              borderRadius: 8,
              border: "1px solid var(--border)",
              background: "var(--surface)",
            }}
          >
            Clear
          </button>
          <button
            type="submit"
            className="tap-target"
            style={{
              padding: "0.5rem 1.25rem",
              borderRadius: 8,
              border: "none",
              background: "var(--accent)",
              color: "white",
              fontWeight: 600,
            }}
          >
            Save
          </button>
        </div>
      </form>
    </div>
  );
}

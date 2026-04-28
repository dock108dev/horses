"use client";

import { useEffect } from "react";

import type { UserTag } from "../lib/types";

const TAGS: { value: UserTag | null; label: string; hint: string }[] = [
  { value: null, label: "Clear", hint: "Remove tag" },
  { value: "single", label: "Single", hint: "Use only this horse this leg" },
  { value: "A", label: "A", hint: "Top contender" },
  { value: "B", label: "B", hint: "Second tier" },
  { value: "C", label: "C", hint: "Backup / chaos coverage" },
  { value: "toss", label: "Toss", hint: "Exclude from tickets" },
  { value: "chaos", label: "Chaos", hint: "Include in chaos tickets" },
];

interface TagPickerProps {
  horseName: string;
  current: UserTag | undefined;
  onSelect: (tag: UserTag | null) => void;
  onClose: () => void;
}

export function TagPicker({
  horseName,
  current,
  onSelect,
  onClose,
}: TagPickerProps) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Tag ${horseName}`}
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
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(420px, 100%)",
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
            Tag horse
          </div>
          <div style={{ fontSize: "1.2rem", fontWeight: 600 }}>{horseName}</div>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: "0.5rem",
          }}
        >
          {TAGS.map((t) => {
            const active = current === t.value || (current == null && t.value == null);
            return (
              <button
                key={t.label}
                type="button"
                className="tap-target"
                onClick={() => {
                  onSelect(t.value);
                  onClose();
                }}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  gap: 2,
                  padding: "0.5rem 0.75rem",
                  borderRadius: 10,
                  border: active
                    ? "2px solid var(--accent)"
                    : "1px solid var(--border)",
                  background: active ? "var(--good-bg)" : "var(--surface-alt)",
                  color: "var(--text)",
                  textAlign: "left",
                }}
              >
                <span style={{ fontWeight: 600 }}>{t.label}</span>
                <span
                  style={{
                    fontSize: "0.7rem",
                    color: "var(--text-muted)",
                    lineHeight: 1.2,
                  }}
                >
                  {t.hint}
                </span>
              </button>
            );
          })}
        </div>

        <button
          type="button"
          className="tap-target"
          onClick={onClose}
          style={{
            alignSelf: "flex-end",
            padding: "0.5rem 1rem",
            borderRadius: 8,
            border: "1px solid var(--border)",
            background: "var(--surface)",
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

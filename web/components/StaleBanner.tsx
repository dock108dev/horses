"use client";

interface StaleBannerProps {
  cachedAt: string | null;
  failedAt: string | null;
  errors?: string[];
}

function fmt(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function StaleBanner({ cachedAt, failedAt, errors }: StaleBannerProps) {
  return (
    <div
      role="status"
      style={{
        background: "var(--warn-bg)",
        color: "var(--warn-fg)",
        border: "1px solid #e6c97a",
        borderRadius: 10,
        padding: "0.6rem 0.9rem",
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <div style={{ fontWeight: 600 }}>
        Showing cached odds from {fmt(cachedAt)} — Refresh failed at{" "}
        {fmt(failedAt)}
      </div>
      {errors && errors.length > 0 ? (
        <div style={{ fontSize: "0.8rem", opacity: 0.85 }}>
          {errors.slice(0, 3).join(" · ")}
        </div>
      ) : null}
    </div>
  );
}

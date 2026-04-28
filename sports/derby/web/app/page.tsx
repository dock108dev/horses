import Link from "next/link";

const cards = [
  {
    day: "friday",
    title: "Friday",
    subtitle: "Kentucky Oaks Pick 5",
    accent: "#b32134",
  },
  {
    day: "saturday",
    title: "Saturday",
    subtitle: "Kentucky Derby Pick 5",
    accent: "#1a4fd0",
  },
] as const;

export default function HomePage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        padding: "2.5rem clamp(1rem, 4vw, 3rem)",
        display: "flex",
        flexDirection: "column",
        gap: "2rem",
      }}
    >
      <header>
        <h1 style={{ margin: 0, fontSize: "2rem", letterSpacing: "-0.01em" }}>
          Derby Pick 5
        </h1>
        <p style={{ margin: "0.25rem 0 0", color: "var(--text-muted)" }}>
          Pick a day to see the 5-leg sequence.
        </p>
      </header>

      <nav
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: "1rem",
        }}
      >
        {cards.map((c) => (
          <Link
            key={c.day}
            href={`/sequence/${c.day}`}
            className="tap-target"
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "0.5rem",
              padding: "1.5rem",
              minHeight: 140,
              borderRadius: 14,
              background: "var(--surface)",
              border: "1px solid var(--border)",
              boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
              color: "var(--text)",
              borderLeft: `8px solid ${c.accent}`,
            }}
          >
            <span
              style={{
                fontSize: "0.85rem",
                fontWeight: 600,
                letterSpacing: "0.05em",
                textTransform: "uppercase",
                color: c.accent,
              }}
            >
              {c.title}
            </span>
            <span style={{ fontSize: "1.4rem", fontWeight: 600 }}>
              {c.subtitle}
            </span>
            <span style={{ color: "var(--text-muted)", marginTop: "auto" }}>
              Open sequence →
            </span>
          </Link>
        ))}
      </nav>
    </main>
  );
}

function value(n: unknown) {
  return typeof n === "number"
    ? n.toLocaleString(undefined, { maximumFractionDigits: 3 })
    : "—";
}

export function WorkerLog({ text }: { text: string }) {
  if (!text.trim()) return <p className="empty">No worker output yet.</p>;
  const lines = text.trimEnd().split("\n");
  return (
    <>
      <div className="log-entries" aria-label="Worker log entries">
        {lines
          .map((line, index) => {
            let entry: Record<string, unknown> | null = null;
            try {
              const parsed = JSON.parse(line);
              if (
                parsed &&
                typeof parsed === "object" &&
                !Array.isArray(parsed)
              )
                entry = parsed;
            } catch {
              /* Plain worker output and partial lines remain readable. */
            }
            if (!entry || typeof entry.generation !== "number")
              return (
                <pre className="log-message" key={index}>
                  {line}
                </pre>
              );
            return (
              <details className="log-entry" key={index}>
                <summary>
                  <strong>Generation {entry.generation}</strong>
                  <span>Best score {value(entry.best_score)}</span>
                  <span>Validation {value(entry.validation_score)}</span>
                  <span>Steps {value(entry.environment_steps)}</span>
                  <span>
                    Throughput {value(entry.steps_per_second)} steps/s
                  </span>
                </summary>
                <pre>{JSON.stringify(entry, null, 2)}</pre>
              </details>
            );
          })
          .reverse()}
      </div>
      <details>
        <summary>Raw worker output</summary>
        <pre className="log-view">{text}</pre>
      </details>
    </>
  );
}

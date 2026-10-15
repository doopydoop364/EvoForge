export function Timestamp({ value }: { value?: number | null }) {
  if (!value || !Number.isFinite(value)) return <>Unavailable</>;
  const date = new Date(value * 1000);
  return <time dateTime={date.toISOString()}>{date.toLocaleString()}</time>;
}

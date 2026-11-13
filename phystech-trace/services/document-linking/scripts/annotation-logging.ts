const levelOrder = { DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40 } as const;
type LogLevel = keyof typeof levelOrder;

const requestedLevel = (process.env.LOG_LEVEL ?? "INFO").toUpperCase();
const configuredLevel: LogLevel = Object.prototype.hasOwnProperty.call(levelOrder, requestedLevel) ? requestedLevel as LogLevel : "INFO";

export function logAnnotationEvent(level: LogLevel, event: string, fields: Record<string, string | number | boolean | undefined> = {}) {
  if (levelOrder[level] < levelOrder[configuredLevel]) return;
  const write = level === "ERROR" ? console.error : level === "WARN" ? console.warn : console.log;
  write(JSON.stringify({ timestamp: new Date().toISOString(), level, event, ...fields }));
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown annotation workflow error";
}

export function logAnnotationFailure(event: string, error: unknown, fields: Record<string, string | number | boolean | undefined> = {}) {
  const operationalFailure = error instanceof SyntaxError || error instanceof TypeError ||
    (typeof error === "object" && error !== null && "code" in error);
  logAnnotationEvent(operationalFailure ? "ERROR" : "WARN", event, {
    ...fields,
    failureKind: operationalFailure ? "operational" : "validation_rejection",
    message: errorMessage(error),
  });
}

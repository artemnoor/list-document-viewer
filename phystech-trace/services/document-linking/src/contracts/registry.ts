export const INPUT_CONTRACT_VERSION = "1.2.0";
export const OUTPUT_CONTRACT_VERSION = "1.2.0";
export const STRUCTURED_EXTRACTION_BASELINE = { repository: "https://github.com/artemnoor/kfz-structured-extraction-", commit: "1e922e284805f2c1b343b4cb369813c8073b67dd", schema_version: "1.2.0" } as const;
export function compatibleExtractionVersion(version: string) { const [major, minor] = version.split(".").map(Number); return major === 1 && Number.isFinite(minor) && minor >= 2; }

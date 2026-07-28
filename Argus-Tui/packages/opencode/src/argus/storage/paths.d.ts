export declare const StoragePaths: {
    /** Top-level data directory (resolved lazily from env var, config, or ~/.argus) */
    readonly basePath: string;
    /** SQLite database path: <basePath>/argus.db */
    readonly db: string;
    /** Credentials file path: <basePath>/credentials.json */
    readonly credentials: string;
    /** Config file path: <basePath>/config.yaml */
    readonly config: string;
    /** Evidence files directory: <basePath>/evidence */
    readonly evidenceDir: string;
    /** Artifacts directory: <basePath>/artifacts */
    readonly artifactsDir: string;
    /** Environment file path: <basePath>/.env */
    readonly env: string;
    /** Engagements directory: <basePath>/engagements */
    readonly engagementsDir: string;
    /** Per-engagement directory: <basePath>/engagements/<id> */
    engagementDir(id: string): string;
    /** Per-engagement database path: <basePath>/engagements/<id>/engagement.db */
    engagementDbPath(id: string): string;
};

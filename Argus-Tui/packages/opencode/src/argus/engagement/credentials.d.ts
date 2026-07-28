export interface CredentialEntry {
    username: string;
    password: string;
    /** Optional JWT/token for OAuth or token-based auth (Gap 2.6) */
    authToken?: string;
    /** Optional auth cookies for session-based auth fallback */
    authCookies?: Array<{
        name: string;
        value: string;
        domain: string;
        path?: string;
        httpOnly?: boolean;
        secure?: boolean;
    }>;
}
export interface CredentialFile {
    roles: Record<string, CredentialEntry>;
    default_role?: string;
}
export declare class CredentialStore {
    private path?;
    private data;
    constructor(path?: string | undefined);
    load(filePath?: string): CredentialFile;
    getCredentials(role: string): CredentialEntry | null;
    getAllCredentials(): Record<string, CredentialEntry>;
    listRoles(): string[];
    getDefaultRole(): string | undefined;
    getDefaultCredentials(): CredentialEntry | null;
    clear(): void;
    save(data: CredentialFile, filePath?: string): void;
    static defaultPath(): string;
}

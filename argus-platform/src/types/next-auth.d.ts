import "next-auth";

declare module "next-auth" {
  interface Session {
    user: {
      id: string;
      email: string;
      orgId: string;
      role: string;
      requires2FAVerification?: boolean;
    };
    requires2FA?: boolean;
  }

  interface User {
    id: string;
    email: string;
    orgId: string;
    role: string;
    requires2FA?: boolean;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id: string;
    orgId: string;
    role: string;
    requires2FA?: boolean;
  }
}

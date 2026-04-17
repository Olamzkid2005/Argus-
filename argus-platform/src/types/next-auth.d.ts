import "next-auth";

declare module "next-auth" {
  interface Session {
    user: {
      id: string;
      email: string;
      orgId: string;
      role: string;
    };
  }

  interface User {
    id: string;
    email: string;
    orgId: string;
    role: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id: string;
    orgId: string;
    role: string;
  }
}

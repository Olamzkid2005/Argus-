import NextAuth from "next-auth";
import { authOptions } from "@/lib/auth";
import { log } from "@/lib/logger";

const handler = NextAuth(authOptions);

log.auth("NextAuth route initialized");

export { handler as GET, handler as POST };

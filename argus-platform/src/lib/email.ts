import nodemailer from 'nodemailer';
import { log } from '@/lib/logger';

const transporter = nodemailer.createTransport({
  host: process.env.SMTP_HOST || 'smtp.gmail.com',
  port: parseInt(process.env.SMTP_PORT || '587'),
  secure: false,
  requireTLS: true,  // Reject if STARTTLS fails (H-20)
  auth: {
    user: process.env.SMTP_USER || process.env.GMAIL_USER,
    pass: process.env.SMTP_PASS || process.env.GMAIL_APP_PASSWORD,
  },
});

export async function sendPasswordResetEmail(to: string, resetToken: string) {
  const baseUrl = process.env.NEXTAUTH_URL || 'http://localhost:3000';
  // Token is sent in the email body only, NOT in the URL (fix C-08).
  // The user visits the reset page and enters the code manually,
  // preventing token leakage via browser history, server logs, or Referer header.
  const resetUrl = `${baseUrl}/auth/reset-password`;

  const mailOptions = {
    from: `"Argus Security" <${process.env.SMTP_USER || process.env.GMAIL_USER || 'noreply@argus.local'}>`,
    to,
    subject: 'Reset Your Argus Password',
    html: `
      <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #6720FF;">Argus Security Platform</h2>
        <p>You requested a password reset. Use the code below to reset your password:</p>
        <div style="background: #F3E8FF; border-radius: 8px; padding: 20px; text-align: center; margin: 16px 0;">
          <code style="font-size: 24px; font-weight: bold; color: #6720FF; letter-spacing: 4px; word-break: break-all;">${resetToken}</code>
        </div>
        <p>Click the button below, then paste or enter the code above to set a new password:</p>
        <a href="${resetUrl}" style="display: inline-block; background: #6720FF; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 16px 0;">
          Reset Password
        </a>
        <p style="color: #666; font-size: 14px;">This code expires in 1 hour. If you didn't request this, ignore this email.</p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;" />
        <p style="color: #999; font-size: 12px;">Argus Security Platform — AI-powered penetration testing</p>
      </div>
    `,
  };

  try {
    const info = await transporter.sendMail(mailOptions);
    log.info("Password reset email sent:", info.messageId);
    return { success: true, messageId: info.messageId };
  } catch (error) {
    log.error("Failed to send password reset email:", error);
    return { success: false, error: (error as Error).message };
  }
}

export async function sendVerificationEmail(to: string, verifyToken: string) {
  const baseUrl = process.env.NEXTAUTH_URL || 'http://localhost:3000';
  // Token is sent in the email body only, NOT in the URL (fix CWE-598, same pattern as C-08).
  // The user visits the verify page and enters the code manually,
  // preventing token leakage via browser history, server logs, or Referer header.
  const verifyUrl = `${baseUrl}/auth/verify`;

  const mailOptions = {
    from: `"Argus Security" <${process.env.SMTP_USER || process.env.GMAIL_USER || 'noreply@argus.local'}>`,
    to,
    subject: 'Verify Your Argus Account',
    html: `
      <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #6720FF;">Welcome to Argus</h2>
        <p>Use the code below to verify your email address:</p>
        <div style="background: #F3E8FF; border-radius: 8px; padding: 20px; text-align: center; margin: 16px 0;">
          <code style="font-size: 24px; font-weight: bold; color: #6720FF; letter-spacing: 4px; word-break: break-all;">${verifyToken}</code>
        </div>
        <p>Click the button below, then paste or enter the code above to verify your account:</p>
        <a href="${verifyUrl}" style="display: inline-block; background: #6720FF; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 16px 0;">
          Verify Email
        </a>
        <p style="color: #666; font-size: 14px;">This code expires in 24 hours. If you didn't create an account, ignore this email.</p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;" />
        <p style="color: #999; font-size: 12px;">Argus Security Platform — AI-powered penetration testing</p>
      </div>
    `,
  };

  try {
    const info = await transporter.sendMail(mailOptions);
    log.info("Verification email sent:", info.messageId);
    return { success: true, messageId: info.messageId };
  } catch (error) {
    log.error("Failed to send verification email:", error);
    return { success: false, error: (error as Error).message };
  }
}

import nodemailer from 'nodemailer';

const transporter = nodemailer.createTransport({
  host: process.env.SMTP_HOST || 'smtp.gmail.com',
  port: parseInt(process.env.SMTP_PORT || '587'),
  secure: false,
  auth: {
    user: process.env.SMTP_USER || process.env.GMAIL_USER,
    pass: process.env.SMTP_PASS || process.env.GMAIL_APP_PASSWORD,
  },
});

export async function sendPasswordResetEmail(to: string, resetToken: string) {
  const baseUrl = process.env.NEXTAUTH_URL || 'http://localhost:3000';
  const resetUrl = `${baseUrl}/auth/reset-password?token=${resetToken}`;

  const mailOptions = {
    from: `"Argus Security" <${process.env.SMTP_USER || process.env.GMAIL_USER || 'noreply@argus.local'}>`,
    to,
    subject: 'Reset Your Argus Password',
    html: `
      <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #6720FF;">Argus Security Platform</h2>
        <p>You requested a password reset. Click the button below to reset your password:</p>
        <a href="${resetUrl}" style="display: inline-block; background: #6720FF; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 16px 0;">
          Reset Password
        </a>
        <p style="color: #666; font-size: 14px;">This link expires in 1 hour. If you didn't request this, ignore this email.</p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;" />
        <p style="color: #999; font-size: 12px;">Argus Security Platform — AI-powered penetration testing</p>
      </div>
    `,
  };

  try {
    const info = await transporter.sendMail(mailOptions);
    console.log('Password reset email sent:', info.messageId);
    return { success: true, messageId: info.messageId };
  } catch (error) {
    console.error('Failed to send password reset email:', error);
    return { success: false, error: (error as Error).message };
  }
}

export async function sendVerificationEmail(to: string, verifyToken: string) {
  const baseUrl = process.env.NEXTAUTH_URL || 'http://localhost:3000';
  const verifyUrl = `${baseUrl}/auth/verify?token=${verifyToken}`;

  const mailOptions = {
    from: `"Argus Security" <${process.env.SMTP_USER || process.env.GMAIL_USER || 'noreply@argus.local'}>`,
    to,
    subject: 'Verify Your Argus Account',
    html: `
      <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #6720FF;">Welcome to Argus</h2>
        <p>Click below to verify your email address:</p>
        <a href="${verifyUrl}" style="display: inline-block; background: #6720FF; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin: 16px 0;">
          Verify Email
        </a>
        <p style="color: #666; font-size: 14px;">This link expires in 24 hours.</p>
      </div>
    `,
  };

  try {
    const info = await transporter.sendMail(mailOptions);
    return { success: true, messageId: info.messageId };
  } catch (error) {
    console.error('Failed to send verification email:', error);
    return { success: false, error: (error as Error).message };
  }
}

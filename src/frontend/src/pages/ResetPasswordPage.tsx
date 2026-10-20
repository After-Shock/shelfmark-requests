import { FormEvent, InputHTMLAttributes, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { completePasswordResetEmail, requestPasswordResetEmail, resetPassword } from '../services/api';
import { theme } from '../theme';
import { withBasePath } from '../utils/basePath';

const Field = ({ label, ...props }: { label: string } & InputHTMLAttributes<HTMLInputElement>) => (
  <div>
    <label className="block text-sm font-medium mb-2">{label}</label>
    <input
      {...props}
      className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors"
      style={{
        backgroundColor: 'var(--input-background)',
        borderColor: 'var(--border-color)',
        color: 'var(--text-color)',
        '--tw-ring-color': theme.primary.turquoise,
      } as React.CSSProperties}
      autoCapitalize="none"
      autoCorrect="off"
      required
    />
  </div>
);

type Mode = 'email' | 'code' | 'token';

export const ResetPasswordPage = ({ emailResetEnabled = false }: { emailResetEnabled?: boolean }) => {
  const logoUrl = withBasePath('/logo.svg');
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const [mode, setMode] = useState<Mode>(token ? 'token' : emailResetEnabled ? 'email' : 'code');
  const [identifier, setIdentifier] = useState('');
  const [username, setUsername] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [done, setDone] = useState(false);

  const run = async (action: () => Promise<string>) => {
    setError(null);
    setMessage(null);
    setIsLoading(true);
    try {
      setMessage(await action());
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Password reset failed');
    } finally {
      setIsLoading(false);
    }
  };

  const checkNewPassword = () => {
    if (password.length < 4) return 'Password must be at least 4 characters';
    if (password !== confirmPassword) return 'Passwords do not match';
    return null;
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (mode === 'email') {
      run(async () => {
        await requestPasswordResetEmail(identifier.trim());
        return 'If that matches an account, we’ve emailed a reset link. It expires in 1 hour. Check your spam folder if it doesn’t arrive in a few minutes.';
      });
      return;
    }
    const problem = checkNewPassword();
    if (problem) {
      setError(problem);
      return;
    }
    if (mode === 'token') {
      run(async () => {
        const result = await completePasswordResetEmail({ token, password });
        const updated = result.updated.length ? ` Also updated: ${result.updated.join(' and ')}.` : '';
        const warn = result.warnings?.length ? ` Some library passwords could not be updated: ${result.warnings.join('; ')}` : '';
        return `Password reset for ${result.username}.${updated}${warn} You can sign in now.`;
      });
      return;
    }
    run(async () => {
      const result = await resetPassword({ username: username.trim(), code: code.trim(), password });
      const warn = result.warnings?.length ? ` Some linked library passwords may need manual update: ${result.warnings.join('; ')}` : '';
      return `Password reset. You can sign in now.${warn}`;
    });
  };

  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
    setMessage(null);
    setDone(false);
  };

  const subtitle = {
    email: 'Enter your username or email and we’ll send you a reset link',
    code: 'Enter the reset code from your admin',
    token: 'Choose a new password',
  }[mode];
  const button = { email: 'Email me a reset link', code: 'Reset Password', token: 'Set new password' }[mode];
  const linkStyle = { color: theme.primary.turquoise };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-8" style={{ backgroundColor: 'var(--background-color)', color: 'var(--text-color)' }}>
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <img src={logoUrl} alt="Logo" className="mx-auto mb-6 w-56 h-56" />
          <h1 className="text-2xl font-semibold">Reset Password</h1>
          <p className="text-sm opacity-70 mt-2">{subtitle}</p>
        </div>
        <div className="rounded-lg shadow-2xl p-8 border" style={{ backgroundColor: 'var(--card-background)', borderColor: 'var(--border-color)', color: 'var(--text-color)' }}>
          {error && <div className="mb-4 p-3 rounded-lg text-sm bg-red-600 text-white">{error}</div>}
          {message && <div className="mb-4 p-3 rounded-lg text-sm bg-green-600 text-white">{message}</div>}

          {mode !== 'code' && (
            <div className="mb-4 p-3 rounded-lg text-sm border" style={{ borderColor: 'var(--border-color)' }}>
              <span className="font-medium">One password for everything.</span>{' '}
              Your new password is also set on your linked Ebooks and Audiobooks accounts.
              Not linked yet? After signing in, open ☰ → Account → <span className="font-medium">Library Access</span>.
            </div>
          )}

          {!done && (
            <form onSubmit={handleSubmit} className="space-y-4">
              {mode === 'email' && (
                <Field label="Username or email" value={identifier} onChange={(e) => setIdentifier(e.target.value)} disabled={isLoading} autoComplete="username" />
              )}
              {mode === 'code' && (
                <>
                  <Field label="Username" value={username} onChange={(e) => setUsername(e.target.value)} disabled={isLoading} />
                  <Field label="Reset Code" value={code} onChange={(e) => setCode(e.target.value)} disabled={isLoading} />
                </>
              )}
              {mode !== 'email' && (
                <>
                  <Field label="New Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={isLoading} autoComplete="new-password" />
                  <Field label="Confirm New Password" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} disabled={isLoading} autoComplete="new-password" />
                </>
              )}
              <button type="submit" disabled={isLoading} className="w-full py-2.5 px-4 rounded-lg font-medium text-white transition-colors disabled:opacity-50" style={{ backgroundColor: theme.button.secondary }}>
                {isLoading ? 'Working...' : button}
              </button>
            </form>
          )}

          <div className="text-center text-sm mt-4 opacity-70 space-y-1">
            {mode === 'email' && (
              <p><button type="button" onClick={() => switchMode('code')} className="font-medium hover:opacity-80" style={linkStyle}>Have a reset code from an admin?</button></p>
            )}
            {mode === 'code' && emailResetEnabled && (
              <p><button type="button" onClick={() => switchMode('email')} className="font-medium hover:opacity-80" style={linkStyle}>Reset by email instead</button></p>
            )}
            {mode === 'token' && error && emailResetEnabled && (
              <p><button type="button" onClick={() => switchMode('email')} className="font-medium hover:opacity-80" style={linkStyle}>Send a new link</button></p>
            )}
            <p>
              {done ? 'Ready?' : 'Remember your password?'}{' '}
              <Link to="/login" className="font-medium hover:opacity-80 transition-opacity" style={linkStyle}>Sign In</Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

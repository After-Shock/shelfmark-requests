import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { resetPassword } from '../services/api';
import { theme } from '../theme';
import { withBasePath } from '../utils/basePath';

export const ResetPasswordPage = () => {
  const logoUrl = withBasePath('/logo.svg');
  const [username, setUsername] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    if (!username.trim() || !code.trim()) {
      setError('Username and reset code are required');
      return;
    }
    if (password.length < 4) {
      setError('Password must be at least 4 characters');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    setIsLoading(true);
    try {
      const result = await resetPassword({ username: username.trim(), code: code.trim(), password });
      const warningText = result.warnings?.length ? ` Some linked library passwords may need manual update: ${result.warnings.join('; ')}` : '';
      setMessage(`Password reset. You can sign in now.${warningText}`);
      setPassword('');
      setConfirmPassword('');
      setCode('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Password reset failed');
    } finally {
      setIsLoading(false);
    }
  };

  const inputStyle = {
    backgroundColor: 'var(--input-background)',
    borderColor: 'var(--border-color)',
    color: 'var(--text-color)',
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-8" style={{ backgroundColor: 'var(--background-color)', color: 'var(--text-color)' }}>
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <img src={logoUrl} alt="Logo" className="mx-auto mb-6 w-72 h-72" />
          <h1 className="text-2xl font-semibold">Reset Password</h1>
          <p className="text-sm opacity-70 mt-2">Enter the reset code from your admin</p>
        </div>
        <div className="rounded-lg shadow-2xl p-8 border" style={{ backgroundColor: 'var(--card-background)', borderColor: 'var(--border-color)', color: 'var(--text-color)' }}>
          {error && <div className="mb-4 p-3 rounded-lg text-sm bg-red-600 text-white">{error}</div>}
          {message && <div className="mb-4 p-3 rounded-lg text-sm bg-green-600 text-white">{message}</div>}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Username</label>
              <input value={username} onChange={(e) => setUsername(e.target.value)} disabled={isLoading} className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors" style={{ ...inputStyle, '--tw-ring-color': theme.primary.turquoise } as React.CSSProperties} autoCapitalize="none" autoCorrect="off" required />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Reset Code</label>
              <input value={code} onChange={(e) => setCode(e.target.value)} disabled={isLoading} className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors" style={{ ...inputStyle, '--tw-ring-color': theme.primary.turquoise } as React.CSSProperties} autoCapitalize="none" autoCorrect="off" required />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">New Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={isLoading} className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors" style={{ ...inputStyle, '--tw-ring-color': theme.primary.turquoise } as React.CSSProperties} autoComplete="new-password" required />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Confirm New Password</label>
              <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} disabled={isLoading} className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 disabled:opacity-50 transition-colors" style={{ ...inputStyle, '--tw-ring-color': theme.primary.turquoise } as React.CSSProperties} autoComplete="new-password" required />
            </div>
            <button type="submit" disabled={isLoading} className="w-full py-2.5 px-4 rounded-lg font-medium text-white transition-colors disabled:opacity-50" style={{ backgroundColor: theme.button.secondary }}>
              {isLoading ? 'Resetting...' : 'Reset Password'}
            </button>
          </form>
          <p className="text-center text-sm mt-4 opacity-70">
            Remember your password? <Link to="/login" className="font-medium hover:opacity-80 transition-opacity" style={{ color: theme.primary.turquoise }}>Sign In</Link>
          </p>
        </div>
      </div>
    </div>
  );
};

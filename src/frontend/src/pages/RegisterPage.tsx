import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { withBasePath } from '../utils/basePath';
import { registerUser } from '../services/api';

interface RegisterPageProps {
  onRegisterComplete: () => void;
}

export const RegisterPage = ({ onRegisterComplete }: RegisterPageProps) => {
  const logoUrl = withBasePath('/logo.svg');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!username.trim()) {
      setError('Username is required');
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
      await registerUser({
        username: username.trim(),
        password,
        email: email.trim() || undefined,
      });
      onRegisterComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
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
    <div
      className="min-h-screen flex items-center justify-center px-4 py-8"
      style={{ backgroundColor: 'var(--background-color)', color: 'var(--text-color)' }}
    >
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <img src={logoUrl} alt="Logo" className="mx-auto mb-6 w-72 h-72" />
          <h1 className="text-2xl font-semibold">Create Account</h1>
          <p className="text-sm opacity-70 mt-2">Sign up to start requesting books</p>
        </div>
        <div
          className="rounded-lg shadow-2xl p-8 border"
          style={{
            backgroundColor: 'var(--card-background)',
            borderColor: 'var(--border-color)',
            color: 'var(--text-color)',
          }}
        >
          {error && (
            <div className="mb-4 p-3 rounded-lg text-sm bg-red-600 text-white">
              {error}
            </div>
          )}
          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label htmlFor="username" className="block text-sm font-medium mb-2">
                Username
              </label>
              <input
                type="text"
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={isLoading}
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50 transition-colors"
                style={inputStyle}
                autoFocus
                autoCapitalize="none"
                autoCorrect="off"
                required
              />
            </div>

            <div className="mb-4">
              <label htmlFor="email" className="block text-sm font-medium mb-2">
                Email <span className="opacity-50">(optional, for notifications)</span>
              </label>
              <input
                type="email"
                id="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isLoading}
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50 transition-colors"
                style={inputStyle}
                placeholder="you@example.com"
              />
            </div>

            <div className="mb-4">
              <label htmlFor="password" className="block text-sm font-medium mb-2">
                Password
              </label>
              <input
                type="password"
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50 transition-colors"
                style={inputStyle}
                autoComplete="new-password"
                required
              />
            </div>

            <div className="mb-6">
              <label htmlFor="confirm-password" className="block text-sm font-medium mb-2">
                Confirm Password
              </label>
              <input
                type="password"
                id="confirm-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                disabled={isLoading}
                className="w-full px-4 py-2.5 rounded-lg border focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50 transition-colors"
                style={inputStyle}
                autoComplete="new-password"
                required
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 px-4 rounded-lg font-medium text-white transition-colors disabled:opacity-50 bg-sky-700 hover:bg-sky-800"
            >
              {isLoading ? 'Creating Account...' : 'Create Account'}
            </button>
          </form>

          <p className="text-center text-sm mt-4 opacity-70">
            Already have an account?{' '}
            <Link to="/login" className="text-sky-600 hover:text-sky-500 font-medium">
              Sign In
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
};

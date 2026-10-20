import { Link } from 'react-router-dom';
import { LoginForm } from '../components/LoginForm';
import { LoginCredentials } from '../types';
import { withBasePath } from '../utils/basePath';
import { theme } from '../theme';

interface LoginPageProps {
  onLogin: (credentials: LoginCredentials) => void;
  error: string | null;
  isLoading: boolean;
  authMode?: string;
  registrationEnabled?: boolean;
  passwordResetEnabled?: boolean;
}

export const LoginPage = ({ onLogin, error, isLoading, authMode, registrationEnabled, passwordResetEnabled }: LoginPageProps) => {
  const logoUrl = withBasePath('/logo.svg');

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4 py-8"
      style={{ backgroundColor: 'var(--background-color)', color: 'var(--text-color)' }}
    >
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <img src={logoUrl} alt="Logo" className="mx-auto mb-6 w-56 h-56" />
          <h1 className="text-2xl font-semibold">Sign in to continue</h1>
        </div>
        <div
          className="rounded-lg shadow-2xl p-8 border"
          style={{
            backgroundColor: 'var(--card-background)',
            borderColor: 'var(--border-color)',
            color: 'var(--text-color)',
          }}
        >
          <LoginForm onSubmit={onLogin} error={error} isLoading={isLoading} authMode={authMode} />

          {authMode === 'builtin' && (
            <p className="text-center text-sm mt-4 opacity-70">
              Already use our Ebooks or Audiobooks app? Sign in with that username and password.
            </p>
          )}

          {authMode === 'builtin' && (
            <p className="text-center text-sm mt-4">
              <Link
                to="/reset-password"
                className="font-medium hover:opacity-80 transition-opacity"
                style={{ color: theme.primary.turquoise }}
              >
                Forgot password?
              </Link>
              {passwordResetEnabled && (
                <span className="block mt-1 text-xs opacity-60">
                  One password covers this site and your linked Ebooks and Audiobooks accounts.
                </span>
              )}
            </p>
          )}

          {registrationEnabled && (
            <p className="text-center text-sm mt-4 opacity-70">
              Don&apos;t have an account?{' '}
              <Link
                to="/register"
                className="font-medium transition-colors"
                style={{
                  color: theme.primary.turquoise,
                }}
                onMouseEnter={(e) => e.currentTarget.style.color = theme.primary.turquoiseLight}
                onMouseLeave={(e) => e.currentTarget.style.color = theme.primary.turquoise}
              >
                Create Account
              </Link>
            </p>
          )}
        </div>
      </div>
    </div>
  );
};


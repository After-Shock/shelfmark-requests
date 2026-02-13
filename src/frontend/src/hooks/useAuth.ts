import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { LoginCredentials } from '../types';
import { login, logout, checkAuth } from '../services/api';

interface UseAuthOptions {
  onLogoutSuccess?: () => void;
  showToast?: (message: string, type: 'info' | 'success' | 'error') => void;
}

interface UseAuthReturn {
  isAuthenticated: boolean;
  authRequired: boolean;
  authChecked: boolean;
  isAdmin: boolean;
  isInitialAdmin: boolean;
  authMode: string;
  needsSetup: boolean;
  registrationEnabled: boolean;
  loginError: string | null;
  isLoggingIn: boolean;
  setIsAuthenticated: (value: boolean) => void;
  handleLogin: (credentials: LoginCredentials) => Promise<void>;
  handleLogout: () => Promise<void>;
  recheckAuth: () => Promise<void>;
}

export function useAuth(options: UseAuthOptions = {}): UseAuthReturn {
  const { onLogoutSuccess, showToast } = options;
  const navigate = useNavigate();

  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [authRequired, setAuthRequired] = useState<boolean>(true);
  const [authChecked, setAuthChecked] = useState<boolean>(false);
  const [isAdmin, setIsAdmin] = useState<boolean>(false);
  const [isInitialAdmin, setIsInitialAdmin] = useState<boolean>(false);
  const [authMode, setAuthMode] = useState<string>('none');
  const [needsSetup, setNeedsSetup] = useState<boolean>(false);
  const [registrationEnabled, setRegistrationEnabled] = useState<boolean>(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);

  const applyAuthResponse = useCallback((response: Awaited<ReturnType<typeof checkAuth>>) => {
    setAuthRequired(response.auth_required !== false);
    setIsAuthenticated(response.authenticated || false);
    setIsAdmin(response.is_admin || false);
    setIsInitialAdmin(response.is_initial_admin || false);
    setAuthMode(response.auth_mode || 'none');
    setNeedsSetup(response.needs_setup || false);
    setRegistrationEnabled(response.registration_enabled || false);
  }, []);

  const recheckAuth = useCallback(async () => {
    try {
      const response = await checkAuth();
      applyAuthResponse(response);
    } catch (error) {
      console.error('Auth re-check failed:', error);
    }
  }, [applyAuthResponse]);

  // Check authentication on mount
  useEffect(() => {
    const verifyAuth = async () => {
      try {
        const response = await checkAuth();
        applyAuthResponse(response);
      } catch (error) {
        console.error('Auth check failed:', error);
        setAuthRequired(true);
        setIsAuthenticated(false);
        setIsAdmin(false);
      } finally {
        setAuthChecked(true);
      }
    };
    verifyAuth();
  }, [applyAuthResponse]);

  const handleLogin = useCallback(async (credentials: LoginCredentials) => {
    setIsLoggingIn(true);
    setLoginError(null);
    try {
      const response = await login(credentials);
      if (response.success) {
        // Re-check auth to get updated admin status from session
        const authResponse = await checkAuth();
        setIsAuthenticated(true);
        setIsAdmin(authResponse.is_admin || false);
        setLoginError(null);
        navigate('/', { replace: true });
      } else {
        setLoginError(response.error || 'Login failed');
      }
    } catch (error) {
      if (error instanceof Error) {
        setLoginError(error.message || 'Login failed');
      } else {
        setLoginError('Login failed');
      }
    } finally {
      setIsLoggingIn(false);
    }
  }, [navigate]);

  const handleLogout = useCallback(async () => {
    try {
      const { logout_url } = await logout();
      if (logout_url?.startsWith('https://') || logout_url?.startsWith('http://')) {
        window.location.href = logout_url;
        return;
      }
      setIsAuthenticated(false);
      onLogoutSuccess?.();
      navigate('/login', { replace: true });
    } catch (error) {
      console.error('Logout failed:', error);
      showToast?.('Logout failed', 'error');
    }
  }, [navigate, onLogoutSuccess, showToast]);

  return {
    isAuthenticated,
    authRequired,
    authChecked,
    isAdmin,
    isInitialAdmin,
    authMode,
    needsSetup,
    registrationEnabled,
    loginError,
    isLoggingIn,
    setIsAuthenticated,
    handleLogin,
    handleLogout,
    recheckAuth,
  };
}

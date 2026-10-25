import type { ComponentType } from 'react';

interface LoginProps {
  mode?: 'login' | 'signup';
  onSuccess?: (user: { email: string }) => void;
  onForgotPassword?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
  onSignUp?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
}

declare const Login: ComponentType<LoginProps>;
export default Login;

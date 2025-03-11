
export function validatePassword(password: string): boolean {
  const re = /^(?=.*\d)(?=.*[a-z])(?=.*[A-Z]).{6,20}$/;
  return re.test(password);
}

export function validateEmail(email: string): boolean {
  const re = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  return re.test(email);
}
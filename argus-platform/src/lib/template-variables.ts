/**
 * Template variable substitution for engagement templates.
 * 
 * Templates can define target_url_pattern with {variable} placeholders,
 * e.g. "https://{subdomain}.example.com/{path}".
 * When applying a template, the user is prompted to fill in variables.
 */
export function extractTemplateVariables(pattern: string): string[] {
  const matches = pattern.match(/\{(\w+)\}/g);
  if (!matches) return [];
  return [...new Set(matches.map(m => m.slice(1, -1)))];
}

export function applyTemplateVariables(
  pattern: string,
  variables: Record<string, string>
): string {
  return pattern.replace(/\{(\w+)\}/g, (_, name) => {
    if (variables[name] !== undefined) return variables[name];
    return `{${name}}`; // leave unfilled variables as-is
  });
}

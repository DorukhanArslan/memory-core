// i18n/index.js: id-keyed dictionaries (TR default, EN toggle) and Intl formatting.
// Test inputs (scenario messages), raw file text, prompt text and payloads are never translated.
import { PROJECT } from '../project.js';
import { setFormatLang } from '../ui/dom.js';
import { TR } from './tr.js';
import { EN } from './en.js';

let LANG = 'tr';
export function setLang(lang) {
  LANG = lang === 'en' ? 'en' : 'tr';
  setFormatLang(LANG);
  document.documentElement.lang = LANG;
}
export function getLang() { return LANG; }

// Name placeholders every string may use; the values come from project.js.
const NAME_PARAMS = {
  project: PROJECT.display, PROJECT: PROJECT.displayUpper, projectName: PROJECT.name,
  projectPackage: PROJECT.package, projectStateDir: PROJECT.stateDir, projectEnvPrefix: PROJECT.envPrefix,
};

/** t('chat.send') or t('toast.saved', { p: 'USER.md' }); the name placeholders are always filled.
 * Unknown ids fall back to TR, then to the id. */
export function t(id, params = null) {
  let s = (LANG === 'en' ? EN[id] : TR[id]) ?? TR[id] ?? id;
  for (const [k, v] of Object.entries({ ...NAME_PARAMS, ...params })) s = s.split(`{${k}}`).join(String(v));
  return s;
}
/** True when the id exists in the active dictionary (used for optional labels such as stage names). */
export function has(id) { return (LANG === 'en' ? EN : TR)[id] !== undefined; }

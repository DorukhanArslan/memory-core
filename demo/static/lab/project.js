// project.js: the project's name forms. The shell page carries them as data-* attributes of
// <body> (demo/app.py SHELL_CONTEXT, from the package's project_name module), so the Lab spells
// the name only through PROJECT and the i18n name placeholders.
const data = document.body.dataset;

export const PROJECT = Object.freeze({
  name: data.projectName, // distribution name: the layout id and the slug of file names
  display: data.projectDisplay, // how the UI writes the product
  displayUpper: data.projectDisplay.toUpperCase(), // the layout chip and label
  package: data.projectPackage, // import package, for module paths
  stateDir: data.projectStateDir, // workspace state directory
  envPrefix: data.projectEnvPrefix, // prefix of every environment name
  labTitle: data.labTitle,
});

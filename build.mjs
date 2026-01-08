import * as esbuild from 'esbuild';

const isWatch = process.argv.includes('--watch');

// TipTap bundle (ES module for import)
const tiptapBuild = {
  entryPoints: ['src/tiptap.js'],
  bundle: true,
  format: 'esm',
  outfile: 'static/js/vendor/tiptap.bundle.js',
  minify: true,
  sourcemap: true,
  target: ['es2020'],
};

// HTMX bundle (IIFE for global script)
const htmxBuild = {
  entryPoints: ['src/htmx.js'],
  bundle: true,
  format: 'iife',
  outfile: 'static/js/vendor/htmx.bundle.js',
  minify: true,
  sourcemap: true,
  target: ['es2020'],
};

// Alpine.js bundle (IIFE for global script)
const alpineBuild = {
  entryPoints: ['src/alpine.js'],
  bundle: true,
  format: 'iife',
  outfile: 'static/js/vendor/alpine.bundle.js',
  minify: true,
  sourcemap: true,
  target: ['es2020'],
};

const builds = [tiptapBuild, htmxBuild, alpineBuild];

if (isWatch) {
  // Watch mode: create contexts for all builds
  const contexts = await Promise.all(
    builds.map(config => esbuild.context(config))
  );
  await Promise.all(contexts.map(ctx => ctx.watch()));
  console.log('Watching for changes...');
} else {
  // Build all bundles
  await Promise.all(builds.map(config => esbuild.build(config)));
  console.log('Build complete:');
  builds.forEach(b => console.log(`  ${b.outfile}`));
}

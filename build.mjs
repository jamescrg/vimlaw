import * as esbuild from 'esbuild';

const isWatch = process.argv.includes('--watch');

const buildOptions = {
  entryPoints: ['src/tiptap.js'],
  bundle: true,
  format: 'esm',
  outfile: 'static/js/vendor/tiptap.bundle.js',
  minify: true,
  sourcemap: true,
  target: ['es2020'],
};

if (isWatch) {
  const ctx = await esbuild.context(buildOptions);
  await ctx.watch();
  console.log('Watching for changes...');
} else {
  await esbuild.build(buildOptions);
  console.log('Build complete: static/js/vendor/tiptap.bundle.js');
}

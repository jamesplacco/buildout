" buildout.vim: ask the Buildout engine from Vim or Neovim. Research only; nothing here can place an order.
"
" Install: copy to ~/.vim/plugin/ (Vim) or ~/.config/nvim/plugin/ (Neovim), or :source it.
" Settings:
"   let g:buildout_python = 'python3'          interpreter that has the buildout package
"   let g:buildout_root   = '~/code/buildout'  repository folder (the engine runs from there)
"
" Commands:
"   :BuildoutThink {question}     the mind's verdict, evidence for and against, the hinge, chains to the book, the decision
"   :BuildoutWhatIf {condition}   a what-if over the belief network, e.g. :BuildoutWhatIf oil spikes, what happens to the book
"   :BuildoutTriage {sharpe} {years} [trials]   a quant's backtest after costs, decay, luck and too little data
"   :BuildoutERP {cash yield} {growth} [rf]     Damodaran's implied equity risk premium
"   :BuildoutDCF {args}           Damodaran's narrative DCF, e.g. :BuildoutDCF --revenue 100 --growth 0.25 --margin 0.30 --target 0.35
"   :BuildoutML / :BuildoutReality   rebuild the ML lab or the reality check into the data folder (needs the network)
" Maps (normal and visual): <Leader>bt think about the word or selection, <Leader>bw what-if on the selection.

if exists('g:loaded_buildout') | finish | endif
let g:loaded_buildout = 1
let g:buildout_python = get(g:, 'buildout_python', 'python3')
let g:buildout_root = get(g:, 'buildout_root', fnamemodify(expand('<sfile>:p:h'), ':h'))

function! s:run(args) abort
  let l:cmd = 'cd ' . shellescape(expand(g:buildout_root)) . ' && ' . g:buildout_python . ' -m buildout ' . a:args
  let l:out = systemlist(l:cmd)
  let l:buf = bufnr('__buildout__')
  if l:buf == -1 || bufwinnr(l:buf) == -1
    botright new __buildout__
    setlocal buftype=nofile bufhidden=hide noswapfile nobuflisted wrap linebreak filetype=buildout
  else
    execute bufwinnr(l:buf) . 'wincmd w'
  endif
  setlocal modifiable
  silent %delete _
  call setline(1, ['buildout ' . a:args, ''] + l:out)
  setlocal nomodifiable
  normal! gg
  nnoremap <buffer> <silent> q :close<CR>
endfunction

function! s:selection() abort
  let [l:a, l:b] = [getpos("'<"), getpos("'>")]
  let l:lines = getline(l:a[1], l:b[1])
  if empty(l:lines) | return '' | endif
  let l:lines[-1] = l:lines[-1][: l:b[2] - (&selection ==# 'inclusive' ? 1 : 2)]
  let l:lines[0] = l:lines[0][l:a[2] - 1:]
  return join(l:lines, ' ')
endfunction

command! -nargs=+ BuildoutThink call s:run('think ' . shellescape(<q-args>))
command! -nargs=+ BuildoutWhatIf call s:run('think ' . shellescape('What if ' . <q-args>))
command! -nargs=+ BuildoutTriage call s:run('triage ' . <q-args>)
command! -nargs=+ BuildoutERP call s:run('erp --cash-yield ' . split(<q-args>)[0] . ' --growth ' . split(<q-args>)[1] . (len(split(<q-args>)) > 2 ? ' --rf ' . split(<q-args>)[2] : ''))
command! -nargs=+ BuildoutDCF call s:run('dcf ' . <q-args>)
command! -nargs=0 BuildoutML call s:run('ml --out site/data')
command! -nargs=0 BuildoutReality call s:run('reality --out site/data')

nnoremap <silent> <Leader>bt :call <SID>run('think ' . shellescape(expand('<cword>')))<CR>
xnoremap <silent> <Leader>bt :<C-u>call <SID>run('think ' . shellescape(<SID>selection()))<CR>
xnoremap <silent> <Leader>bw :<C-u>call <SID>run('think ' . shellescape('What if ' . <SID>selection()))<CR>

augroup buildout_syntax
  autocmd!
  autocmd FileType buildout syntax match buildoutPro /^\s*+ .*/ | syntax match buildoutCon /^\s*- .*/ | syntax match buildoutKey /^\s*\(hinge\|chain\|decision\|what-if\):/
  autocmd FileType buildout highlight default link buildoutPro DiffAdd | highlight default link buildoutCon DiffDelete | highlight default link buildoutKey Title
augroup END

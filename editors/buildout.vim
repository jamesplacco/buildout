" buildout.vim: ask the Buildout engine from Vim or Neovim. Research only; nothing here can place an order.
"
" Install: copy to ~/.vim/plugin/ (Vim) or ~/.config/nvim/plugin/ (Neovim), or :source it.
" Commands run in the background (Vim 8.1 jobs or Neovim jobs); older Vims fall back to system() and wait.
" Every result, and every error, lands in one scratch buffer named buildout://out.
"
" Options (all optional; set them in your vimrc):
"   g:buildout_python        interpreter that has the buildout package (default 'python3')
"   g:buildout_root          repository folder the engine runs from. Default: walk up from the current file to
"                            a folder holding pyproject.toml and buildout/, else the folder above this plugin's folder
"   g:buildout_prefix        prefix for the maps below (default '<Leader>b')
"   g:buildout_no_mappings   1 skips every default map (the <Plug>(buildout-...) maps stay available)
"   g:buildout_sync          1 runs commands with system() and waits (the tests use this)
"   g:buildout_focus         0 keeps the cursor in your window instead of the results window (default 1)
"   g:buildout_height        height of the results window (default 15)
"   g:buildout_engine_out    output folder for :BuildoutEngine (default 'out')
"   g:buildout_log_size      how many entries g:buildout_history keeps (default 50)
"   g:buildout_history       the query log, newest first; each entry is a list of arguments. Read or clear it freely
"
" Commands:
"   :Buildout {sub} [args]          any subcommand; Tab completes subcommand names, their flags and values
"   :BuildoutThink [question]       the mind's verdict (prompts when empty; with a range, asks about those lines)
"   :BuildoutWhatIf [condition]     a what-if over the belief network
"   :BuildoutBonds [y10 [y30 [front]]]   Treasury ETFs repriced at yields in percent (prompts when empty;
"                                   an empty 30-year moves with the 10-year; front is parallel or anchored)
"   :BuildoutHistory [query]        a month, a year, an episode or 'now' from the chronicle
"   :BuildoutTA [ticker]            technicals; default the ticker under the cursor
"   :BuildoutFA [ticker]            fundamentals; default the ticker under the cursor
"   :BuildoutEngine [dir]           run the offline engines into dir (default g:buildout_engine_out)
"   :BuildoutEngineList             the engine registry
"   :BuildoutDoctor                 check the setup
"   :BuildoutBench                  time the engine
"   :BuildoutTriage {sharpe} {years} [trials]   a backtest after costs, decay, luck and too little data
"   :BuildoutERP {cash yield} {growth} [rf]     Damodaran's implied equity risk premium
"   :BuildoutDCF {args}             Damodaran's narrative DCF, e.g. --revenue 100 --growth 0.25 --margin 0.3 --target 0.35
"   :BuildoutML / :BuildoutReality  rebuild the ML lab or the reality check into site/data (needs the network)
"   :BuildoutRerun                  run the last command again
"   :BuildoutStop                   stop the running command
"   :BuildoutOpen                   show the results window again
"   :BuildoutLog                    the query log in buildout://log; <CR> on an entry reruns it.  :BuildoutLog! clears it
"
" Maps (P is the prefix; each map is also <Plug>(buildout-NAME), NAME in brackets):
"   Pt  think: prompt; in Visual mode the selection [think]     Pw  think about the word under the cursor [think-word]
"   Pl  think about the current line [think-line]                Pi  what-if: prompt; in Visual mode the selection [what-if]
"   Pb  bonds [bonds]       Ph  history [history]     Pa  ta for the ticker under the cursor [ta]
"   Pf  fa for the ticker under the cursor [fa]       Pe  engine run [engine]    Pd  doctor [doctor]   Pm  bench [bench]
"   Pr  rerun [rerun]       PL  query log [log]       Pg  :Buildout prompt [prompt]
"   Ps  stop [stop]         Po  open results [open]
"
" In buildout://out: q closes, r reruns, y copies the output to the unnamed register, n and p jump to the next and
" previous section, s stops a running command.

if exists('g:loaded_buildout') | finish | endif
let g:loaded_buildout = 1

let s:save_cpo = &cpo
set cpo&vim

if !exists('g:buildout_history') | let g:buildout_history = [] | endif

let s:plugin_root = fnamemodify(expand('<sfile>:p:h'), ':h')
let s:out_name = 'buildout://out'
let s:log_name = 'buildout://log'
let s:header = 4
let s:gen = 0
let s:cur = {'gen': 0, 'running': 0, 'buf': -1, 'lines': 0}
let s:last = {}

let s:subcommands = ['atlas', 'bench', 'bonds', 'brain', 'buyside', 'capex', 'connect', 'cost', 'dcf', 'decide', 'demo',
      \ 'doctor', 'engine', 'erp', 'fa', 'feeds', 'history', 'journal', 'kalshi', 'labs', 'macro', 'market', 'mcp',
      \ 'mind', 'ml', 'ooda', 'portfolio', 'positions', 'reality', 'reason', 'research', 'rl', 'run', 'sources', 'status', 'ta',
      \ 'think', 'triage']
let s:flags = {
      \ 'think': ['--json', '--data'],
      \ 'bonds': ['--y10', '--y30', '--front', '--live', '--out'],
      \ 'decide': ['--out', '--quick', '--json'],
      \ 'portfolio': ['--out', '--quick'],
      \ 'engine': ['--out', '--only', '--list'],
      \ 'triage': ['--published', '--cost-bps', '--turns', '--vol', '--skew', '--kurt', '--periods'],
      \ 'erp': ['--level', '--cash-yield', '--growth', '--rf'],
      \ 'dcf': ['--revenue', '--growth', '--margin', '--target', '--years-to-target', '--sales-to-capital', '--wacc',
      \         '--wacc-mature', '--rf', '--p-fail', '--shares', '--debt', '--cash'],
      \ 'positions': ['--write'],
      \ 'market': ['--out', '--tickers', '--no-fundamentals'],
      \ 'capex': ['--ua', '--json'],
      \ 'connect': ['--out'],
      \ 'mcp': ['--data', '--config'],
      \ 'research': ['--out', '--data'],
      \ 'run': ['--config', '--out'],
      \ 'cost': ['--config'],
      \ 'macro': ['--out', '--csv'],
      \ }
for s:name in ['demo', 'status', 'brain', 'buyside', 'reason', 'mind', 'labs', 'ml', 'reality', 'rl']
  let s:flags[s:name] = ['--out']
endfor
unlet s:name

" ---------------------------------------------------------------- options and paths

function! s:opt(name, default) abort
  return get(g:, 'buildout_' . a:name, a:default)
endfunction

function! s:strip(text) abort
  return substitute(a:text, '^\s\+\|\s\+$', '', 'g')
endfunction

function! s:root() abort
  let l:root = s:opt('root', '')
  if !empty(l:root)
    let l:root = fnamemodify(expand(l:root), ':p')
    return l:root =~# '.[\\/]$' ? l:root[: -2] : l:root
  endif
  if bufname('%') =~# '^buildout://' && has_key(s:last, 'root')
    return s:last.root
  endif
  let l:dir = empty(&buftype) ? expand('%:p:h') : ''
  if empty(l:dir) || !isdirectory(l:dir) | let l:dir = getcwd() | endif
  while 1
    if filereadable(l:dir . '/pyproject.toml') && isdirectory(l:dir . '/buildout')
      return l:dir
    endif
    let l:up = fnamemodify(l:dir, ':h')
    if l:up ==# l:dir | break | endif
    let l:dir = l:up
  endwhile
  return s:plugin_root
endfunction

function! s:quote(arg) abort
  return a:arg =~# '^[A-Za-z0-9_./:%+=,^@-]\+$' ? a:arg : "'" . substitute(a:arg, "'", "'\\\\''", 'g') . "'"
endfunction

function! s:display(args) abort
  return join(map(copy(a:args), 's:quote(v:val)'), ' ')
endfunction

" Split a command line the way a shell would: spaces separate, quotes group, backslash escapes.
function! s:split(text) abort
  let [l:args, l:cur, l:has, l:quote, l:i, l:n] = [[], '', 0, '', 0, strlen(a:text)]
  while l:i < l:n
    let l:c = a:text[l:i]
    if l:quote ==# "'"
      if l:c ==# "'" | let l:quote = '' | else | let l:cur .= l:c | endif
    elseif l:quote ==# '"'
      if l:c ==# '"'
        let l:quote = ''
      elseif l:c ==# '\' && l:i + 1 < l:n && a:text[l:i + 1] =~# '["\\]'
        let l:i += 1
        let l:cur .= a:text[l:i]
      else
        let l:cur .= l:c
      endif
    elseif l:c ==# ' ' || l:c ==# "\t"
      if l:has | call add(l:args, l:cur) | let [l:cur, l:has] = ['', 0] | endif
    elseif l:c ==# "'" || l:c ==# '"'
      let [l:quote, l:has] = [l:c, 1]
    elseif l:c ==# '\' && l:i + 1 < l:n
      let l:i += 1
      let [l:cur, l:has] = [l:cur . a:text[l:i], 1]
    else
      let [l:cur, l:has] = [l:cur . l:c, 1]
    endif
    let l:i += 1
  endwhile
  if l:has | call add(l:args, l:cur) | endif
  return l:args
endfunction

" ---------------------------------------------------------------- the results buffer

function! s:open(name) abort
  let l:buf = bufnr('^' . a:name . '$')
  let l:win = bufwinnr(l:buf)
  if l:win != -1
    execute l:win . 'wincmd w'
    return l:buf
  endif
  let l:height = s:opt('height', 15)
  if l:buf == -1
    execute 'silent keepalt botright ' . l:height . 'new'
    setlocal buftype=nofile bufhidden=hide noswapfile nobuflisted
    execute 'silent keepalt file ' . fnameescape(a:name)
    call s:setup(a:name)
    return bufnr('%')
  endif
  execute 'silent keepalt botright ' . l:height . 'split'
  execute 'silent keepalt buffer ' . l:buf
  return l:buf
endfunction

function! s:setup(name) abort
  setlocal nomodifiable wrap linebreak nonumber norelativenumber nolist nospell foldcolumn=0
  if exists('&signcolumn') | setlocal signcolumn=no | endif
  nnoremap <buffer> <silent> q :<C-u>call <SID>close()<CR>
  if a:name ==# s:log_name
    nnoremap <buffer> <silent> <CR> :<C-u>call <SID>log_pick()<CR>
    setlocal filetype=buildoutlog
    return
  endif
  nnoremap <buffer> <silent> r :<C-u>call <SID>rerun()<CR>
  nnoremap <buffer> <silent> y :<C-u>call <SID>yank()<CR>
  nnoremap <buffer> <silent> n :<C-u>call <SID>section(1)<CR>
  nnoremap <buffer> <silent> p :<C-u>call <SID>section(-1)<CR>
  nnoremap <buffer> <silent> s :<C-u>call <SID>stop(0)<CR>
  setlocal filetype=buildout
endfunction

" Replace line lnum (lnum > 0) or append at the end (lnum == 0), whether or not the buffer is in view.
function! s:put(buf, lnum, lines) abort
  if a:buf < 0 || !bufexists(a:buf) | return | endif
  let l:lines = map(type(a:lines) == type([]) ? copy(a:lines) : [a:lines], 'substitute(v:val, "\r$", "", "")')
  call setbufvar(a:buf, '&modifiable', 1)
  if exists('*appendbufline')
    if a:lnum > 0
      call setbufline(a:buf, a:lnum, l:lines)
    else
      call appendbufline(a:buf, '$', l:lines)
    endif
  elseif bufnr('%') == a:buf
    if a:lnum > 0 | call setline(a:lnum, l:lines) | else | call append('$', l:lines) | endif
  endif
  call setbufvar(a:buf, '&modifiable', 0)
endfunction

function! s:render(args, root, python) abort
  let l:buf = s:open(s:out_name)
  setlocal modifiable
  silent %delete _
  call setline(1, ['buildout ' . s:display(a:args), 'in ' . a:root . '  with ' . a:python, 'running...', ''])
  setlocal nomodifiable
  call cursor(1, 1)
  return l:buf
endfunction

function! s:close() abort
  if winnr('$') > 1
    close
  elseif bufexists(bufnr('#')) && bufnr('#') != bufnr('%')
    buffer #
  else
    enew
  endif
endfunction

function! s:yank() abort
  let l:lines = getline(s:header + 1, '$')
  call setreg('"', l:lines, 'l')
  echo 'buildout: copied ' . len(l:lines) . ' lines'
endfunction

" A section starts at an unindented line or at an indented label such as 'hinge:' or 'decision:'.
function! s:section(dir) abort
  let l:pat = '\%>' . s:header . 'l\%(^\S\|^\s\+\a[[:alnum:]_-]*:\%(\s\|$\)\)'
  for l:i in range(v:count1)
    if !search(l:pat, a:dir > 0 ? 'W' : 'bW') | break | endif
  endfor
endfunction

" ---------------------------------------------------------------- running

function! s:remember(args) abort
  if type(g:buildout_history) != type([]) | let g:buildout_history = [] | endif
  call filter(g:buildout_history, 'v:val !=# a:args')
  call insert(g:buildout_history, copy(a:args), 0)
  let l:size = s:opt('log_size', 50)
  if len(g:buildout_history) > l:size | call remove(g:buildout_history, l:size, -1) | endif
endfunction

function! s:run(args) abort
  call s:start(a:args, s:root())
endfunction

function! s:start(args, root) abort
  call s:stop(1)
  let s:gen += 1
  let s:last = {'args': copy(a:args), 'root': a:root}
  call s:remember(a:args)
  let l:python = expand(s:opt('python', 'python3'))
  let l:origin = win_getid()
  let s:cur = {'gen': s:gen, 'running': 1, 'lines': 0, 'start': reltime(), 'exit': -1, 'closed': 0,
        \ 'partial': {'stdout': '', 'stderr': ''}, 'job': 0, 'kind': '', 'timer': -1}
  let s:cur.buf = s:render(a:args, a:root, l:python)
  if !executable(l:python)
    call s:fail(['python executable not found: ' . l:python,
          \ 'Set g:buildout_python to an interpreter that has the buildout package.'])
  elseif !isdirectory(a:root . '/buildout')
    call s:fail(['no buildout package under ' . a:root,
          \ 'Set g:buildout_root to the repository folder (the one with pyproject.toml and buildout/).'])
  else
    call s:launch([l:python, '-m', 'buildout'] + a:args, a:root)
  endif
  if !s:opt('focus', 1) | call win_gotoid(l:origin) | endif
endfunction

function! s:launch(argv, root) abort
  let l:gen = s:cur.gen
  if !s:opt('sync', 0) && has('nvim')
    let s:cur.kind = 'nvim'
    let s:cur.job = jobstart(a:argv, {'cwd': a:root,
          \ 'on_stdout': function('s:nvim_out', [l:gen]), 'on_stderr': function('s:nvim_out', [l:gen]),
          \ 'on_exit': function('s:nvim_exit', [l:gen])})
    if s:cur.job <= 0 | call s:fail(['could not start ' . a:argv[0]]) | return | endif
  elseif !s:opt('sync', 0) && exists('*job_start') && has('patch-8.0.0902')
    let s:cur.kind = 'vim'
    let s:cur.job = job_start(a:argv, {'cwd': a:root, 'in_io': 'null', 'out_mode': 'nl', 'err_mode': 'nl',
          \ 'out_cb': function('s:vim_out', [l:gen]), 'err_cb': function('s:vim_out', [l:gen]),
          \ 'exit_cb': function('s:vim_exit', [l:gen]), 'close_cb': function('s:vim_close', [l:gen])})
    if job_status(s:cur.job) ==# 'fail' | call s:fail(['could not start ' . a:argv[0]]) | return | endif
  else
    let s:cur.kind = 'sync'
    let l:cd = has('win32') ? 'cd /d ' : 'cd '
    let l:cmd = l:cd . shellescape(a:root) . ' && ' . join(map(copy(a:argv), 'shellescape(v:val)'), ' ') . ' 2>&1'
    let l:out = split(system(l:cmd), "\n", 1)
    let l:code = v:shell_error
    if !empty(l:out) && l:out[-1] ==# '' | call remove(l:out, -1) | endif
    call s:output(l:out)
    call s:finish(l:code)
    return
  endif
  if has('timers')
    let s:cur.timer = timer_start(1000, function('s:tick', [l:gen]), {'repeat': -1})
  endif
endfunction

function! s:output(lines) abort
  if empty(a:lines) | return | endif
  call s:put(s:cur.buf, 0, a:lines)
  let s:cur.lines += len(a:lines)
endfunction

function! s:elapsed() abort
  return printf('%.2fs', reltimefloat(reltime(s:cur.start)))
endfunction

function! s:tick(gen, timer) abort
  if a:gen != s:cur.gen || !s:cur.running | call timer_stop(a:timer) | return | endif
  call s:put(s:cur.buf, 3, 'running... ' . printf('%.0fs', reltimefloat(reltime(s:cur.start))))
endfunction

function! s:finish(code) abort
  if !s:cur.running | return | endif
  let s:cur.running = 0
  if s:cur.timer != -1 | call timer_stop(s:cur.timer) | endif
  if s:cur.lines == 0 | call s:put(s:cur.buf, 0, '(no output)') | endif
  if a:code == 0
    call s:put(s:cur.buf, 3, 'done in ' . s:elapsed())
  else
    call s:put(s:cur.buf, 3, 'failed: exit ' . a:code . ' after ' . s:elapsed())
    call s:put(s:cur.buf, 0, ['', 'buildout: the command exited with status ' . a:code . '; see the output above.'])
  endif
endfunction

function! s:fail(msgs) abort
  let s:cur.running = 0
  if s:cur.timer != -1 | call timer_stop(s:cur.timer) | endif
  call s:put(s:cur.buf, 3, 'error: ' . a:msgs[0])
  call s:put(s:cur.buf, 0, map(copy(a:msgs), '"error: " . v:val'))
endfunction

function! s:show_error(args, msgs) abort
  call s:stop(1)
  let s:gen += 1
  let s:cur = {'gen': s:gen, 'running': 1, 'lines': 0, 'start': reltime(), 'timer': -1, 'kind': ''}
  let s:cur.buf = s:render(a:args, s:root(), expand(s:opt('python', 'python3')))
  call s:fail(a:msgs)
endfunction

function! s:vim_out(gen, channel, msg) abort
  if a:gen == s:cur.gen | call s:output([a:msg]) | endif
endfunction

function! s:vim_exit(gen, job, code) abort
  if a:gen != s:cur.gen | return | endif
  let s:cur.exit = a:code
  if s:cur.closed | call s:finish(a:code) | endif
endfunction

function! s:vim_close(gen, channel) abort
  if a:gen != s:cur.gen | return | endif
  let s:cur.closed = 1
  if s:cur.exit != -1 | call s:finish(s:cur.exit) | endif
endfunction

function! s:nvim_out(gen, id, data, event) abort
  if a:gen != s:cur.gen | return | endif
  let l:data = copy(a:data)
  let l:data[0] = s:cur.partial[a:event] . l:data[0]
  let s:cur.partial[a:event] = remove(l:data, -1)
  call s:output(l:data)
endfunction

function! s:nvim_exit(gen, id, code, event) abort
  if a:gen != s:cur.gen | return | endif
  call s:output(filter(values(s:cur.partial), '!empty(v:val)'))
  call s:finish(a:code)
endfunction

function! s:stop(quiet) abort
  if !s:cur.running || s:cur.kind ==# 'sync' || s:cur.kind ==# ''
    if !a:quiet | echo 'buildout: nothing is running' | endif
    return
  endif
  let l:job = s:cur.job
  if s:cur.kind ==# 'nvim' | call jobstop(l:job) | else | call job_stop(l:job) | endif
  let s:cur.running = 0
  if s:cur.timer != -1 | call timer_stop(s:cur.timer) | endif
  call s:put(s:cur.buf, 3, 'stopped after ' . s:elapsed())
  let s:gen += 1
  let s:cur.gen = s:gen
endfunction

function! s:rerun() abort
  if empty(s:last)
    call s:show_error(['rerun'], ['nothing has run yet in this session'])
    return
  endif
  call s:start(s:last.args, s:last.root)
endfunction

" ---------------------------------------------------------------- the commands

function! s:ask(text, prompt) abort
  let l:text = s:strip(a:text)
  if empty(l:text)
    call inputsave()
    let l:text = s:strip(input(a:prompt))
    call inputrestore()
    redraw
  endif
  return l:text
endfunction

function! s:think(text, range, line1, line2, whatif) abort
  let l:text = a:text
  if empty(s:strip(l:text)) && a:range > 0
    let l:text = join(map(getline(a:line1, a:line2), 's:strip(v:val)'), ' ')
  endif
  let l:text = s:ask(l:text, a:whatif ? 'What if: ' : 'Think: ')
  if empty(l:text) | return | endif
  if a:whatif && l:text !~? '^what if\>' | let l:text = 'What if ' . l:text | endif
  call s:run(['think', l:text])
endfunction

function! s:selection() abort
  let [l:a, l:b] = [getpos("'<"), getpos("'>")]
  let l:lines = getline(l:a[1], l:b[1])
  if empty(l:lines) | return '' | endif
  if visualmode() !=# 'V'
    let l:last = l:lines[-1]
    if l:b[2] <= strlen(l:last)
      let l:lines[-1] = &selection ==# 'exclusive' ? strpart(l:last, 0, l:b[2] - 1)
            \ : matchstr(l:last, '^.*\%' . l:b[2] . 'c.')
    endif
    let l:lines[0] = strpart(l:lines[0], l:a[2] - 1)
  endif
  return join(map(l:lines, 's:strip(v:val)'), ' ')
endfunction

" The current line without its indent, comment leader or list bullet.
function! s:line_text() abort
  return substitute(getline('.'), '^\s*\%(#\+\|"\|//\|--\|;\+\|%\|\*\|[-+]\)\=\s*', '', '')
endfunction

function! s:clean_ticker(raw) abort
  let l:t = toupper(substitute(a:raw, '^[$(\[{<"'']\+\|[)\]}>"'',.;:!?]\+$', '', 'g'))
  return l:t =~# '^\^\=[A-Z0-9][A-Z0-9.=-]\{0,11}$' ? l:t : ''
endfunction

function! s:ticker(sub, text) abort
  let l:t = s:clean_ticker(s:strip(a:text))
  if empty(a:text)
    let l:t = s:clean_ticker(expand('<cWORD>'))
    if empty(l:t) | let l:t = s:clean_ticker(expand('<cword>')) | endif
  endif
  if empty(l:t) | let l:t = s:clean_ticker(s:ask('', toupper(a:sub) . ' ticker: ')) | endif
  if empty(l:t)
    call s:show_error([a:sub], ['no ticker under the cursor or given; try :Buildout' . toupper(a:sub) . ' NVDA'])
    return
  endif
  call s:run([a:sub, l:t])
endfunction

function! s:number(text) abort
  let l:t = substitute(s:strip(a:text), '%$', '', '')
  return l:t =~# '^-\=\%(\d\+\%(\.\d*\)\=\|\.\d\+\)$' ? l:t : ''
endfunction

function! s:bonds(...) abort
  let l:y10 = a:0 >= 1 ? a:1 : s:ask('', '10-year yield in percent (empty: the snapshot curve): ')
  if empty(s:strip(l:y10)) | call s:run(['bonds']) | return | endif
  if empty(s:number(l:y10))
    call s:show_error(['bonds'], ['the 10-year yield must be a number in percent, like 4 or 4.25; got "' . l:y10 . '"'])
    return
  endif
  let l:args = ['bonds', '--y10', s:number(l:y10)]
  let l:y30 = a:0 >= 2 ? a:2 : a:0 == 1 ? '' : s:ask('', '30-year yield in percent (empty: moves with the 10-year): ')
  if !empty(s:strip(l:y30)) && l:y30 !=# '-'
    if empty(s:number(l:y30))
      call s:show_error(l:args, ['the 30-year yield must be a number in percent, like 4.5; got "' . l:y30 . '"'])
      return
    endif
    let l:args += ['--y30', s:number(l:y30)]
  endif
  if a:0 >= 3
    if index(['parallel', 'anchored'], a:3) < 0
      call s:show_error(l:args, ['the front end must be parallel or anchored; got "' . a:3 . '"'])
      return
    endif
    let l:args += ['--front', a:3]
  endif
  call s:run(l:args)
endfunction

function! s:history(text) abort
  let l:q = s:ask(a:text, "History (a month, a year, an episode or 'now'): ")
  if !empty(l:q) | call s:run(['history', l:q]) | endif
endfunction

function! s:erp(...) abort
  if a:0 < 2
    call s:show_error(['erp'], ['usage: :BuildoutERP {cash yield} {growth} [rf], as fractions, e.g. 0.035 0.06'])
    return
  endif
  call s:run(['erp', '--cash-yield', a:1, '--growth', a:2] + (a:0 > 2 ? ['--rf', a:3] : []))
endfunction

function! s:complete(lead, line, pos) abort
  let l:words = s:split(strpart(a:line, 0, a:pos))
  let l:done = len(l:words) - (empty(a:lead) ? 1 : 2)
  if l:done <= 0
    return filter(copy(s:subcommands), 'stridx(v:val, a:lead) == 0')
  endif
  let l:sub = l:words[1]
  let l:prev = empty(a:lead) ? l:words[-1] : l:words[-2]
  if l:prev ==# '--front'
    return filter(['parallel', 'anchored'], 'stridx(v:val, a:lead) == 0')
  elseif l:prev =~# '^--\%(out\|data\)$'
    return getcompletion(a:lead, 'dir')
  elseif a:lead !~# '^-' && (index(['positions', 'journal'], l:sub) >= 0 || l:prev =~# '^--\%(config\|csv\|write\|json\)$')
    return getcompletion(a:lead, 'file')
  endif
  return filter(copy(get(s:flags, l:sub, [])), 'stridx(v:val, a:lead) == 0')
endfunction

function! s:log(bang) abort
  if a:bang
    let g:buildout_history = []
    echo 'buildout: query log cleared'
    return
  endif
  call s:open(s:log_name)
  let l:lines = ['buildout query log, newest first (<CR> reruns, q closes)', '']
  let l:i = 0
  for l:entry in g:buildout_history
    let l:i += 1
    call add(l:lines, printf('%3d  %s', l:i, s:display(l:entry)))
  endfor
  if l:i == 0 | call add(l:lines, '(empty: nothing has run yet)') | endif
  setlocal modifiable
  silent %delete _
  call setline(1, l:lines)
  setlocal nomodifiable
  call cursor(min([3, line('$')]), 1)
endfunction

function! s:log_pick() abort
  let l:idx = line('.') - 3
  if l:idx < 0 || l:idx >= len(g:buildout_history) | return | endif
  let l:args = copy(g:buildout_history[l:idx])
  call s:close()
  call s:run(l:args)
endfunction

function! s:show() abort
  let l:buf = s:open(s:out_name)
  if line('$') == 1 && empty(getline(1))
    call s:put(l:buf, 1, ['buildout', '', 'nothing has run yet', ''])
  endif
endfunction

command! -nargs=+ -complete=customlist,s:complete Buildout call s:run(s:split(<q-args>))
command! -nargs=* -range BuildoutThink call s:think(<q-args>, <range>, <line1>, <line2>, 0)
command! -nargs=* -range BuildoutWhatIf call s:think(<q-args>, <range>, <line1>, <line2>, 1)
command! -nargs=* BuildoutBonds call s:bonds(<f-args>)
command! -nargs=* BuildoutHistory call s:history(<q-args>)
command! -nargs=? BuildoutTA call s:ticker('ta', <q-args>)
command! -nargs=? BuildoutFA call s:ticker('fa', <q-args>)
command! -nargs=? -complete=dir BuildoutEngine call s:run(['engine', '--out', empty(<q-args>) ? s:opt('engine_out', 'out') : <q-args>])
command! -nargs=0 BuildoutEngineList call s:run(['engine', '--list'])
command! -nargs=0 BuildoutDoctor call s:run(['doctor'])
command! -nargs=0 BuildoutBench call s:run(['bench'])
command! -nargs=+ BuildoutTriage call s:run(['triage'] + s:split(<q-args>))
command! -nargs=+ BuildoutERP call s:erp(<f-args>)
command! -nargs=+ BuildoutDCF call s:run(['dcf'] + s:split(<q-args>))
command! -nargs=0 BuildoutML call s:run(['ml', '--out', 'site/data'])
command! -nargs=0 BuildoutReality call s:run(['reality', '--out', 'site/data'])
command! -nargs=0 BuildoutRerun call s:rerun()
command! -nargs=0 BuildoutStop call s:stop(0)
command! -nargs=0 BuildoutOpen call s:show()
command! -nargs=0 -bang BuildoutLog call s:log(<bang>0)

" ---------------------------------------------------------------- maps

nnoremap <silent> <Plug>(buildout-think) :<C-u>call <SID>think('', 0, 0, 0, 0)<CR>
xnoremap <silent> <Plug>(buildout-think) :<C-u>call <SID>think(<SID>selection(), 0, 0, 0, 0)<CR>
nnoremap <silent> <Plug>(buildout-think-word) :<C-u>call <SID>think(expand('<cword>'), 0, 0, 0, 0)<CR>
nnoremap <silent> <Plug>(buildout-think-line) :<C-u>call <SID>think(<SID>line_text(), 0, 0, 0, 0)<CR>
nnoremap <silent> <Plug>(buildout-what-if) :<C-u>call <SID>think('', 0, 0, 0, 1)<CR>
xnoremap <silent> <Plug>(buildout-what-if) :<C-u>call <SID>think(<SID>selection(), 0, 0, 0, 1)<CR>
nnoremap <silent> <Plug>(buildout-bonds) :<C-u>call <SID>bonds()<CR>
nnoremap <silent> <Plug>(buildout-history) :<C-u>call <SID>history('')<CR>
nnoremap <silent> <Plug>(buildout-ta) :<C-u>call <SID>ticker('ta', '')<CR>
nnoremap <silent> <Plug>(buildout-fa) :<C-u>call <SID>ticker('fa', '')<CR>
nnoremap <silent> <Plug>(buildout-engine) :<C-u>BuildoutEngine<CR>
nnoremap <silent> <Plug>(buildout-doctor) :<C-u>BuildoutDoctor<CR>
nnoremap <silent> <Plug>(buildout-bench) :<C-u>BuildoutBench<CR>
nnoremap <silent> <Plug>(buildout-rerun) :<C-u>call <SID>rerun()<CR>
nnoremap <silent> <Plug>(buildout-log) :<C-u>call <SID>log(0)<CR>
nnoremap <silent> <Plug>(buildout-stop) :<C-u>call <SID>stop(0)<CR>
nnoremap <silent> <Plug>(buildout-open) :<C-u>call <SID>show()<CR>
nnoremap <Plug>(buildout-prompt) :<C-u>Buildout<Space>

if !get(g:, 'buildout_no_mappings', 0)
  let s:prefix = get(g:, 'buildout_prefix', '<Leader>b')
  for [s:mode, s:key, s:plug] in [['n', 't', 'think'], ['x', 't', 'think'], ['n', 'w', 'think-word'],
        \ ['n', 'l', 'think-line'], ['n', 'i', 'what-if'], ['x', 'i', 'what-if'], ['n', 'b', 'bonds'],
        \ ['n', 'h', 'history'], ['n', 'a', 'ta'], ['n', 'f', 'fa'], ['n', 'e', 'engine'], ['n', 'd', 'doctor'],
        \ ['n', 'm', 'bench'], ['n', 'r', 'rerun'], ['n', 'L', 'log'], ['n', 'g', 'prompt'], ['n', 's', 'stop'],
        \ ['n', 'o', 'open']]
    if !hasmapto('<Plug>(buildout-' . s:plug . ')', s:mode) && empty(maparg(s:prefix . s:key, s:mode))
      execute s:mode . 'map ' . s:prefix . s:key . ' <Plug>(buildout-' . s:plug . ')'
    endif
  endfor
  unlet s:prefix s:mode s:key s:plug
endif

" ---------------------------------------------------------------- highlighting

function! s:highlights() abort
  highlight default link buildoutCommand Statement
  highlight default link buildoutWhere Comment
  highlight default link buildoutStatus Comment
  highlight default link buildoutFailed ErrorMsg
  highlight default link buildoutHeading Title
  highlight default link buildoutLabel Identifier
  highlight default link buildoutPercent Number
  execute 'highlight default link buildoutPositive ' . (hlexists('Added') ? 'Added' : 'DiffAdd')
  execute 'highlight default link buildoutNegative ' . (hlexists('Removed') ? 'Removed' : 'DiffDelete')
  highlight default link buildoutError ErrorMsg
  highlight default link buildoutLogNumber LineNr
endfunction

function! s:syntax() abort
  syntax clear
  syntax match buildoutCommand /\%1l.*/
  syntax match buildoutWhere /\%2l.*/
  syntax match buildoutStatus /\%3l.*/
  syntax match buildoutFailed /\%3l\%(failed\|error\|stopped\).*/
  syntax match buildoutHeading /\%>4l^\S.*/ contains=buildoutPercent,buildoutPositive,buildoutNegative
  syntax match buildoutLabel /\%>4l^\s\+\zs\a[[:alnum:]_-]*:\ze\%(\s\|$\)/
  syntax match buildoutPercent /\<\d\+\%(\.\d\+\)\=%/
  syntax match buildoutPositive /\%(^\|[^[:alnum:]_.]\)\zs+\d\+\%([.,]\d\+\)*%\=/
  syntax match buildoutNegative /\%(^\|[^[:alnum:]_.]\)\zs-\d\+\%([.,]\d\+\)*%\=/
  syntax match buildoutPositive /\%>4l^\s*\zs+\ze\s/
  syntax match buildoutNegative /\%>4l^\s*\zs-\ze\s/
  syntax match buildoutError /\%>4l^\%(error: \|buildout: \|Traceback \|\a*Error: \).*/
  call s:highlights()
  let b:current_syntax = 'buildout'
endfunction

function! s:log_syntax() abort
  syntax clear
  syntax match buildoutHeading /\%1l.*/
  syntax match buildoutLogNumber /^\s*\d\+\ze  /
  call s:highlights()
  let b:current_syntax = 'buildoutlog'
endfunction

augroup buildout_plugin
  autocmd!
  autocmd FileType,Syntax buildout call s:syntax()
  autocmd FileType,Syntax buildoutlog call s:log_syntax()
  autocmd ColorScheme * call s:highlights()
augroup END

let &cpo = s:save_cpo
unlet s:save_cpo

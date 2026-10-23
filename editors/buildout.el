;;; buildout.el --- Ask the Buildout engine from Emacs  -*- lexical-binding: t; -*-

;; Version: 0.17
;; Package-Requires: ((emacs "25.1"))
;; Keywords: tools

;;; Commentary:

;; Research only: nothing here can place an order.
;;
;; Every command runs python -m buildout in the background (never
;; freezing Emacs) and shows the command, the elapsed time and the
;; output, or a clear error, in one buffer named *buildout*.
;;
;; Install: put this file on your load-path, then
;;   (require 'buildout)
;;   (buildout-mode 1)                         ; C-c b prefix everywhere
;; or bind the prefix map wherever you like:
;;   (global-set-key (kbd "C-c b") 'buildout-command-map)
;;
;; Options (M-x customize-group RET buildout RET):
;;   buildout-python          interpreter that has the buildout package ("python3")
;;   buildout-root            repository folder; nil walks up from the current file to a folder
;;                            holding pyproject.toml and buildout/, else the folder above this file's
;;   buildout-engine-out      output folder for `buildout-engine' ("out")
;;   buildout-select-window   non-nil moves point to the results window (t)
;;   buildout-log-size        how many commands `buildout-log' remembers (50)
;;
;; Commands, with their keys under the prefix:
;;   g  buildout-run             any subcommand: complete its name, then type its arguments
;;   t  buildout-think           ask the mind (the region, if active; otherwise a prompt)
;;   w  buildout-think-at-point  the word at point (with C-u, the current line)
;;   l  buildout-think-line      the current line
;;   i  buildout-what-if         a what-if over the belief network (the region, if active)
;;   b  buildout-bonds           Treasury ETFs at the 10-year and 30-year yields you type, in percent
;;                               (an empty 30-year moves with the 10-year; C-u also asks for the front end)
;;   h  buildout-history         a month, a year, an episode or "now" from the chronicle
;;   a  buildout-ta              technicals for the ticker at point (C-u asks)
;;   f  buildout-fa              fundamentals for the ticker at point (C-u asks)
;;   e  buildout-engine          run the offline engines into `buildout-engine-out' (C-u asks)
;;   E  buildout-engine-list     the engine registry
;;   d  buildout-doctor          check the setup
;;   m  buildout-bench           time the engine
;;   r  buildout-rerun           run the last command again
;;   L  buildout-log             pick a recent command and run it again
;;   s  buildout-stop            stop the running command
;;   o  buildout-show            show the results buffer
;;   T  buildout-triage   P  buildout-erp   D  buildout-dcf   M  buildout-ml   R  buildout-reality
;;   M-x buildout-think-region   ask about the text between point and mark
;;
;; In *buildout*: q quits the window, r or g reruns, y copies the
;; output, n and p move to the next and previous section, s stops.
;;
;; Minibuffer history: `buildout-query-history' holds the questions
;; and queries typed; `buildout-run-log' holds the commands run.

;;; Code:

(require 'subr-x)

(defgroup buildout nil
  "Ask the Buildout research engine."
  :group 'tools
  :prefix "buildout-")

(defcustom buildout-python "python3"
  "Interpreter that has the buildout package: a name on `exec-path' or a full path."
  :type 'string)

(defcustom buildout-root nil
  "The Buildout repository folder the engine runs from.
When nil, walk up from the current file to a folder that holds both
pyproject.toml and buildout/, and fall back to the folder above the
one that holds this file."
  :type '(choice (const :tag "Find it from the current file" nil) directory))

(defcustom buildout-engine-out "out"
  "Output folder for `buildout-engine', relative to the repository."
  :type 'string)

(defcustom buildout-select-window t
  "Non-nil means move point to the results window when a command starts."
  :type 'boolean)

(defcustom buildout-log-size 50
  "How many recent commands `buildout-run-log' keeps."
  :type 'integer)

(defface buildout-positive '((t :inherit success))
  "Face for numbers with a plus sign and for evidence in favor.")

(defface buildout-negative '((t :inherit error))
  "Face for numbers with a minus sign and for evidence against.")

(defface buildout-heading '((t :inherit font-lock-function-name-face :weight bold))
  "Face for unindented lines of output.")

(defface buildout-label '((t :inherit font-lock-keyword-face))
  "Face for labels such as hinge: and decision:.")

(defface buildout-percent '((t :inherit font-lock-constant-face))
  "Face for unsigned percentages.")

(defface buildout-command '((t :inherit font-lock-type-face :weight bold))
  "Face for the command line at the top of the results buffer.")

(defconst buildout-buffer-name "*buildout*"
  "Name of the results buffer.")

(defconst buildout-subcommands
  '("atlas" "bench" "bonds" "brain" "buyside" "capex" "connect" "cost" "dcf" "decide" "demo" "doctor"
    "engine" "erp" "fa" "feeds" "history" "journal" "kalshi" "labs" "macro" "market" "mcp"
    "mind" "ml" "ooda" "portfolio" "positions" "reality" "reason" "research" "rl" "run" "sources" "status"
    "ta" "think" "triage")
  "Subcommands of python -m buildout, offered by `buildout-run'.")

(defconst buildout--plugin-root
  (let ((file (or load-file-name (bound-and-true-p byte-compile-current-file) buffer-file-name)))
    (if file
        (file-name-directory (directory-file-name (file-name-directory (expand-file-name file))))
      default-directory))
  "The folder above the one holding this file.")

(defvar buildout-query-history nil
  "Minibuffer history of questions and queries.")

(defvar buildout-command-history nil
  "Minibuffer history of subcommand names for `buildout-run'.")

(defvar buildout-args-history nil
  "Minibuffer history of argument lines for `buildout-run'.")

(defvar buildout-yield-history nil
  "Minibuffer history of yields for `buildout-bonds'.")

(defvar buildout-ticker-history nil
  "Minibuffer history of tickers for `buildout-ta' and `buildout-fa'.")

(defvar buildout-run-log nil
  "Recent commands, newest first; each is a list of argument strings.")

(defvar buildout--last nil
  "Plist (:args ARGS :root ROOT) of the last command.")

(defvar buildout--process nil
  "The running engine process, or nil.")

(defvar-local buildout--output-start nil
  "Marker where the output begins in the results buffer.")

(defvar-local buildout--status-marker nil
  "Marker at the status line of the results buffer.")

;;;; Paths and arguments

(defun buildout--repo-p (dir)
  "Non-nil when DIR holds pyproject.toml and the buildout package."
  (and (file-exists-p (expand-file-name "pyproject.toml" dir))
       (file-directory-p (expand-file-name "buildout" dir))))

(defun buildout--find-root (&optional start)
  "Return the repository folder, as a directory name, for START.
START defaults to the current file's folder.  `buildout-root' wins
when set."
  (if buildout-root
      (file-name-as-directory (expand-file-name buildout-root))
    (let* ((from (or start
                     (and (derived-mode-p 'buildout-results-mode) (plist-get buildout--last :root))
                     (and buffer-file-name (file-name-directory buffer-file-name))
                     default-directory))
           (found (locate-dominating-file from #'buildout--repo-p)))
      (file-name-as-directory (expand-file-name (or found buildout--plugin-root))))))

(defun buildout--quote (arg)
  "Quote ARG for display the way a shell would read it back."
  (if (string-match-p "\\`[A-Za-z0-9_./:%+=,^@-]+\\'" arg)
      arg
    (concat "'" (replace-regexp-in-string "'" "'\\''" arg t t) "'")))

(defun buildout--display (args)
  "Return ARGS, a list of strings, as one shell-style line."
  (mapconcat #'buildout--quote args " "))

(defun buildout--split (text)
  "Split TEXT into a list of arguments the way a shell would.
Spaces separate, single and double quotes group, backslash escapes."
  (let ((args nil) (cur nil) (has nil) (q nil) (i 0) (n (length text)))
    (while (< i n)
      (let ((c (aref text i)))
        (cond
         ((eql q ?\')
          (if (eql c ?\') (setq q nil) (push c cur)))
         ((eql q ?\")
          (cond ((eql c ?\") (setq q nil))
                ((and (eql c ?\\) (< (1+ i) n) (memq (aref text (1+ i)) '(?\" ?\\)))
                 (setq i (1+ i))
                 (push (aref text i) cur))
                (t (push c cur))))
         ((memq c '(?\s ?\t ?\n))
          (when has
            (push (apply #'string (nreverse cur)) args)
            (setq cur nil has nil)))
         ((memq c '(?\' ?\"))
          (setq q c has t))
         ((and (eql c ?\\) (< (1+ i) n))
          (setq i (1+ i))
          (push (aref text i) cur)
          (setq has t))
         (t (push c cur) (setq has t))))
      (setq i (1+ i)))
    (when has (push (apply #'string (nreverse cur)) args))
    (nreverse args)))

(defun buildout--blank-p (x)
  "Non-nil when X is nil or a string of only whitespace."
  (or (null x) (and (stringp x) (string-empty-p (string-trim x)))))

(defun buildout--number (x)
  "Return X, a number or a string such as \"4.25%\", as a plain number string, or nil."
  (cond
   ((numberp x) (number-to-string x))
   ((stringp x)
    (let ((s (string-remove-suffix "%" (string-trim x))))
      (when (string-match-p "\\`-?\\(?:[0-9]+\\(?:\\.[0-9]*\\)?\\|\\.[0-9]+\\)\\'" s) s)))))

(defun buildout--clean-ticker (raw)
  "Return RAW as an upper-case ticker such as NVDA or BRK.B, or nil."
  (when (stringp raw)
    (let ((tk (upcase (replace-regexp-in-string
                       "\\`[$([{<\"']+\\|[])}>\"',.;:!?]+\\'" "" (string-trim raw))))
          (case-fold-search nil))
      (when (string-match-p "\\`\\^?[A-Z0-9][A-Z0-9.=-]\\{0,11\\}\\'" tk) tk))))

(defun buildout--ticker-at-point ()
  "Return the ticker at point, or nil."
  (save-excursion
    (skip-chars-backward "A-Za-z0-9.^=$-")
    (let ((beg (point)))
      (skip-chars-forward "A-Za-z0-9.^=$-")
      (buildout--clean-ticker (buffer-substring-no-properties beg (point))))))

(defun buildout--line-text ()
  "Return the current line without its indent, comment leader or list bullet."
  (replace-regexp-in-string
   "\\`[ \t]*\\(?:#+\\|//\\|--\\|;+\\|%\\|\\*\\|[-+]\\)?[ \t]*" ""
   (buffer-substring-no-properties (line-beginning-position) (line-end-position))))

;;;; The results buffer

(defun buildout--after-header (regexp)
  "Return a font-lock matcher for REGEXP that skips the header lines."
  (lambda (limit)
    (let (found)
      (while (and (not found) (re-search-forward regexp limit t))
        (when (or (null buildout--output-start) (>= (match-beginning 0) buildout--output-start))
          (setq found t)))
      found)))

(defconst buildout--section-regexp
  "^\\(?:[^ \t\n]\\|[ \t]+[[:alpha:]][[:alnum:]_-]*:\\(?:[ \t]\\|$\\)\\)"
  "Where a section starts: an unindented line, or an indented label such as hinge:.")

(defconst buildout--font-lock-keywords
  (list
   (list (buildout--after-header "^\\(?:error: \\|buildout: \\|Traceback \\|[[:alpha:]]*Error: \\).*")
         0 ''error)
   (list (buildout--after-header "^[^ \t\n].*") 0 ''buildout-heading)
   (list (buildout--after-header "^[ \t]+\\([[:alpha:]][[:alnum:]_-]*:\\)\\(?:[ \t]\\|$\\)")
         1 ''buildout-label)
   (list (buildout--after-header "^[ \t]*\\(\\+\\)[ \t]") 1 ''buildout-positive 'prepend)
   (list (buildout--after-header "^[ \t]*\\(-\\)[ \t]") 1 ''buildout-negative 'prepend)
   (list (buildout--after-header "\\(?:^\\|[^[:alnum:]_.]\\)\\(\\+[0-9]+\\(?:[.,][0-9]+\\)*%?\\)")
         1 ''buildout-positive 'prepend)
   (list (buildout--after-header "\\(?:^\\|[^[:alnum:]_.]\\)\\(-[0-9]+\\(?:[.,][0-9]+\\)*%?\\)")
         1 ''buildout-negative 'prepend)
   (list (buildout--after-header "\\(?:^\\|[^-+[:alnum:]_.]\\)\\([0-9]+\\(?:\\.[0-9]+\\)?%\\)")
         1 ''buildout-percent 'prepend))
  "Highlighting for `buildout-results-mode'.")

(defvar buildout-results-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map "q" #'quit-window)
    (define-key map "r" #'buildout-rerun)
    (define-key map "y" #'buildout-copy-output)
    (define-key map "n" #'buildout-next-section)
    (define-key map "p" #'buildout-previous-section)
    (define-key map "s" #'buildout-stop)
    map)
  "Keymap for `buildout-results-mode'.")

(define-derived-mode buildout-results-mode special-mode "Buildout"
  "Major mode for results from the Buildout engine.
\\{buildout-results-mode-map}"
  (setq-local font-lock-defaults '(buildout--font-lock-keywords t))
  (setq-local revert-buffer-function #'buildout--revert)
  (setq-local truncate-lines nil))

(defun buildout--revert (&rest _)
  "Rerun the last command; the `revert-buffer-function' of the results buffer."
  (buildout-rerun))

(defun buildout--buffer ()
  "Return the results buffer, creating it in `buildout-results-mode' if needed."
  (let ((buf (get-buffer-create buildout-buffer-name)))
    (with-current-buffer buf
      (unless (derived-mode-p 'buildout-results-mode) (buildout-results-mode)))
    buf))

(defun buildout--render (args root python)
  "Clear the results buffer and write the header for ARGS run from ROOT with PYTHON."
  (let ((buf (buildout--buffer)))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (propertize (concat "buildout " (buildout--display args)) 'font-lock-face 'buildout-command)
                "\n"
                (propertize (format "in %s  with %s" (directory-file-name root) python) 'font-lock-face 'shadow)
                "\n")
        (setq buildout--status-marker (point-marker))
        (insert (propertize "running..." 'font-lock-face 'shadow) "\n\n")
        (setq buildout--output-start (point-marker))
        (goto-char (point-min))))
    (let ((win (display-buffer buf)))
      (when (and win buildout-select-window) (select-window win)))
    buf))

(defun buildout--set-status (buf text face)
  "Replace the status line of BUF with TEXT in FACE."
  (when (buffer-live-p buf)
    (with-current-buffer buf
      (when buildout--status-marker
        (let ((inhibit-read-only t))
          (save-excursion
            (goto-char buildout--status-marker)
            (delete-region (point) (line-end-position))
            (insert (propertize text 'font-lock-face face))))))))

(defun buildout--append (buf text &optional face)
  "Append TEXT, in FACE when given, to the end of BUF."
  (when (buffer-live-p buf)
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (save-excursion
          (goto-char (point-max))
          (insert (if face (propertize text 'font-lock-face face) text)))))))

(defun buildout--fail (buf messages)
  "Show MESSAGES, a list of strings, as the error in BUF."
  (buildout--set-status buf (concat "error: " (car messages)) 'error)
  (dolist (m messages)
    (buildout--append buf (concat "error: " m "\n") 'error)))

(defun buildout--show-error (args messages)
  "Show MESSAGES as the result of ARGS without running anything."
  (buildout-stop t)
  (buildout--fail (buildout--render args (buildout--find-root) buildout-python) messages))

;;;; Running

(defun buildout--remember (args)
  "Put ARGS at the front of `buildout-run-log'."
  (setq buildout-run-log (cons (copy-sequence args) (delete args buildout-run-log)))
  (when (> (length buildout-run-log) (max 1 buildout-log-size))
    (setcdr (nthcdr (1- (max 1 buildout-log-size)) buildout-run-log) nil)))

(defun buildout--filter (proc string)
  "Append STRING from PROC to its results buffer."
  (when (eq proc buildout--process)
    (buildout--append (process-buffer proc) (replace-regexp-in-string "\r" "" string))))

(defun buildout--sentinel (proc _event)
  "Write the status of PROC once it has finished."
  (when (memq (process-status proc) '(exit signal))
    (let ((buf (process-buffer proc))
          (secs (float-time (time-subtract (current-time) (process-get proc 'buildout-start))))
          (code (process-exit-status proc)))
      (process-put proc 'buildout-done t)
      (when (eq proc buildout--process) (setq buildout--process nil))
      (when (and (buffer-live-p buf) (not (process-get proc 'buildout-stopped)))
        (with-current-buffer buf
          (let ((inhibit-read-only t))
            (save-excursion
              (goto-char (point-max))
              (cond ((= (point) buildout--output-start) (insert "(no output)\n"))
                    ((not (bolp)) (insert "\n"))))))
        (if (and (eq (process-status proc) 'exit) (zerop code))
            (buildout--set-status buf (format "done in %.2fs" secs) 'shadow)
          (buildout--set-status buf (format "failed: exit %d after %.2fs" code secs) 'error)
          (buildout--append buf (format "\nbuildout: the command exited with status %d; see the output above.\n" code)
                            'error))))))

(defun buildout--run (args &optional root)
  "Run python -m buildout ARGS from ROOT and show the result in *buildout*.
ARGS is a list of strings.  ROOT defaults to `buildout--find-root'.
Return the process, or nil when the command could not start; the
reason is then shown in the results buffer."
  (let ((root (file-name-as-directory (or root (buildout--find-root))))
        (python buildout-python))
    (buildout-stop t)
    (setq buildout--last (list :args (copy-sequence args) :root root))
    (buildout--remember args)
    (let ((buf (buildout--render args root python))
          (exe (executable-find python)))
      (cond
       ((not exe)
        (buildout--fail buf (list (format "python executable not found: %s" python)
                                  "Set `buildout-python' to an interpreter that has the buildout package."))
        nil)
       ((not (file-directory-p (expand-file-name "buildout" root)))
        (buildout--fail buf (list (format "no buildout package under %s" root)
                                  "Set `buildout-root' to the repository folder (the one with pyproject.toml and buildout/)."))
        nil)
       (t
        (condition-case err
            (let* ((default-directory root)
                   (proc (make-process :name "buildout" :buffer buf
                                       :command (append (list exe "-m" "buildout") args)
                                       :connection-type 'pipe :noquery t :coding 'utf-8
                                       :filter #'buildout--filter :sentinel #'buildout--sentinel)))
              (process-put proc 'buildout-start (current-time))
              (setq buildout--process proc))
          (error (buildout--fail buf (list (format "could not start %s: %s" exe (error-message-string err))))
                 nil)))))))

;;;; Commands

(defun buildout--read (prompt)
  "Read a query with PROMPT, trimmed; the empty string means cancel."
  (string-trim (read-string prompt nil 'buildout-query-history)))

(defun buildout--think (text whatif)
  "Ask the mind about TEXT; with WHATIF, as a what-if."
  (let ((text (string-trim (replace-regexp-in-string "[ \t\n\r]+" " " (or text "")))))
    (unless (string-empty-p text)
      (when (and whatif (not (let ((case-fold-search t)) (string-match-p "\\`what if\\_>" text))))
        (setq text (concat "What if " text)))
      (buildout--run (list "think" text)))))

(defun buildout--region-or-read (prompt)
  "Return the active region's text, or read one with PROMPT."
  (if (use-region-p)
      (buffer-substring-no-properties (region-beginning) (region-end))
    (buildout--read prompt)))

;;;###autoload
(defun buildout-run (subcommand &optional args)
  "Run the Buildout SUBCOMMAND with ARGS, a list of strings or one string.
Interactively, complete the subcommand name, then read its arguments
as one line split the way a shell would."
  (interactive
   (let ((sub (completing-read "Buildout subcommand: " buildout-subcommands nil nil nil
                               'buildout-command-history)))
     (list sub (read-string (format "buildout %s " sub) nil 'buildout-args-history))))
  (let ((args (if (stringp args) (buildout--split args) args))
        (sub (string-trim (or subcommand ""))))
    (if (string-empty-p sub)
        (buildout--show-error '("run") '("no subcommand given; try think, bonds, history or doctor"))
      (buildout--run (cons sub args)))))

;;;###autoload
(defun buildout-think (question)
  "Ask the mind QUESTION and show its verdict, evidence, hinge and decision.
Interactively, use the active region, or else read a question."
  (interactive (list (buildout--region-or-read "Think: ")))
  (buildout--think question nil))

;;;###autoload
(defun buildout-think-region (beg end)
  "Ask the mind about the text between BEG and END."
  (interactive "r")
  (buildout--think (buffer-substring-no-properties beg end) nil))

;;;###autoload
(defun buildout-think-at-point (&optional line)
  "Ask the mind about the word at point; with LINE (\\[universal-argument]), the current line."
  (interactive "P")
  (buildout--think (if line (buildout--line-text) (or (thing-at-point 'word t) "")) nil))

;;;###autoload
(defun buildout-think-line ()
  "Ask the mind about the current line."
  (interactive)
  (buildout--think (buildout--line-text) nil))

;;;###autoload
(defun buildout-what-if (condition)
  "Set CONDITION in the belief network and see what settles where.
Interactively, use the active region, or else read a condition."
  (interactive (list (buildout--region-or-read "What if: ")))
  (buildout--think condition t))

;;;###autoload
(defun buildout-bonds (y10 &optional y30 front)
  "Reprice every Treasury ETF at a 10-year yield Y10 and a 30-year yield Y30.
Yields are in percent, as numbers or strings such as \"4.25\".  An
empty Y10 shows the snapshot curve; an empty or nil Y30 moves with
the 10-year.  FRONT is \"parallel\" or \"anchored\"; with a prefix
argument the command asks for it."
  (interactive
   (let* ((y10 (read-string "10-year yield in percent (empty: the snapshot curve): " nil
                            'buildout-yield-history))
          (y30 (if (buildout--blank-p y10) ""
                 (read-string "30-year yield in percent (empty: moves with the 10-year): " nil
                              'buildout-yield-history)))
          (front (when current-prefix-arg
                   (completing-read "Front end: " '("parallel" "anchored") nil t))))
     (list y10 y30 front)))
  (let ((y10s (buildout--number y10))
        (y30s (buildout--number y30))
        (front (unless (buildout--blank-p front) front)))
    (cond
     ((buildout--blank-p y10) (buildout--run (list "bonds")))
     ((not y10s)
      (buildout--show-error '("bonds")
                            (list (format "the 10-year yield must be a number in percent, like 4 or 4.25; got %S" y10))))
     ((and (not (buildout--blank-p y30)) (not y30s))
      (buildout--show-error (list "bonds" "--y10" y10s)
                            (list (format "the 30-year yield must be a number in percent, like 4.5; got %S" y30))))
     ((and front (not (member front '("parallel" "anchored"))))
      (buildout--show-error (list "bonds" "--y10" y10s)
                            (list (format "the front end must be parallel or anchored; got %S" front))))
     (t (buildout--run (append (list "bonds" "--y10" y10s)
                               (when y30s (list "--y30" y30s))
                               (when front (list "--front" front))))))))

;;;###autoload
(defun buildout-history (query)
  "Show QUERY from the chronicle: a month, a year, an episode or \"now\"."
  (interactive (list (buildout--read "History (a month, a year, an episode or 'now'): ")))
  (unless (buildout--blank-p query)
    (buildout--run (list "history" (string-trim query)))))

(defun buildout--read-ticker (sub)
  "Return the ticker at point for SUB, or read one (always with a prefix argument)."
  (let ((at (buildout--ticker-at-point)))
    (if (and at (not current-prefix-arg))
        at
      (read-string (format "%s ticker%s: " (upcase sub) (if at (format " (default %s)" at) ""))
                   nil 'buildout-ticker-history at))))

(defun buildout--ticker-command (sub ticker)
  "Run SUB (ta or fa) for TICKER, or explain in the results buffer why not."
  (let ((tk (buildout--clean-ticker ticker)))
    (if tk
        (buildout--run (list sub tk))
      (buildout--show-error (list sub)
                            (list (format "no ticker at point or given; try M-x buildout-%s and type NVDA" sub))))))

;;;###autoload
(defun buildout-ta (ticker)
  "Technicals for TICKER, by default the ticker at point."
  (interactive (list (buildout--read-ticker "ta")))
  (buildout--ticker-command "ta" ticker))

;;;###autoload
(defun buildout-fa (ticker)
  "Fundamentals for TICKER, by default the ticker at point."
  (interactive (list (buildout--read-ticker "fa")))
  (buildout--ticker-command "fa" ticker))

;;;###autoload
(defun buildout-engine (&optional dir)
  "Run the offline engines into DIR (default `buildout-engine-out').
With a prefix argument, ask for the folder."
  (interactive (list (when current-prefix-arg (read-directory-name "Engine output folder: "))))
  (buildout--run (list "engine" "--out" (or dir buildout-engine-out))))

;;;###autoload
(defun buildout-engine-list ()
  "Show the engine registry."
  (interactive)
  (buildout--run (list "engine" "--list")))

;;;###autoload
(defun buildout-doctor ()
  "Check the Buildout setup: interpreter, packages, data and keys."
  (interactive)
  (buildout--run (list "doctor")))

;;;###autoload
(defun buildout-bench ()
  "Time the Buildout engine."
  (interactive)
  (buildout--run (list "bench")))

;;;###autoload
(defun buildout-triage (sharpe years trials)
  "Triage a backtest: SHARPE over YEARS after TRIALS variants tried."
  (interactive "nBacktest Sharpe: \nnYears: \nnVariants tried: ")
  (buildout--run (list "triage" (number-to-string sharpe) (number-to-string years) (number-to-string trials))))

;;;###autoload
(defun buildout-erp (cash-yield growth rf)
  "Damodaran's implied equity risk premium from CASH-YIELD, GROWTH and RF, as fractions."
  (interactive "nCash yield (0.035): \nnGrowth (0.06): \nnRisk-free (0.0513): ")
  (buildout--run (list "erp" "--cash-yield" (number-to-string cash-yield) "--growth" (number-to-string growth)
                       "--rf" (number-to-string rf))))

;;;###autoload
(defun buildout-dcf (revenue growth margin target)
  "Damodaran's narrative DCF from REVENUE, GROWTH, MARGIN now and TARGET margin."
  (interactive "nRevenue: \nnHigh growth (0.25): \nnMargin now (0.30): \nnTarget margin (0.35): ")
  (buildout--run (list "dcf" "--revenue" (number-to-string revenue) "--growth" (number-to-string growth)
                       "--margin" (number-to-string margin) "--target" (number-to-string target))))

;;;###autoload
(defun buildout-ml ()
  "Rebuild the ML lab into site/data (needs the network)."
  (interactive)
  (buildout--run (list "ml" "--out" "site/data")))

;;;###autoload
(defun buildout-reality ()
  "Rebuild the reality check into site/data (needs the network)."
  (interactive)
  (buildout--run (list "reality" "--out" "site/data")))

;;;###autoload
(defun buildout-rerun ()
  "Run the last Buildout command again, from the same folder."
  (interactive)
  (if buildout--last
      (buildout--run (plist-get buildout--last :args) (plist-get buildout--last :root))
    (buildout--show-error '("rerun") '("nothing has run yet in this session"))))

;;;###autoload
(defun buildout-log (args)
  "Run ARGS, a command picked from `buildout-run-log', again."
  (interactive
   (let ((table (mapcar (lambda (a) (cons (buildout--display a) a)) buildout-run-log)))
     (list (when table
             (cdr (assoc (completing-read "Run again: " (mapcar #'car table) nil t) table))))))
  (if args
      (buildout--run args)
    (buildout--show-error '("log") '("the log is empty: nothing has run yet in this session"))))

;;;###autoload
(defun buildout-stop (&optional quiet)
  "Stop the running Buildout command.
With QUIET, say nothing when nothing is running."
  (interactive)
  (let ((proc buildout--process))
    (if (not (process-live-p proc))
        (unless quiet (message "buildout: nothing is running"))
      (process-put proc 'buildout-stopped t)
      (setq buildout--process nil)
      (delete-process proc)
      (buildout--set-status (process-buffer proc)
                            (format "stopped after %.2fs"
                                    (float-time (time-subtract (current-time) (process-get proc 'buildout-start))))
                            'error))))

;;;###autoload
(defun buildout-show ()
  "Show the results buffer."
  (interactive)
  (let ((win (display-buffer (buildout--buffer))))
    (when (and win buildout-select-window) (select-window win))))

(defun buildout-copy-output ()
  "Copy the output in the results buffer, without the header, to the kill ring."
  (interactive)
  (let ((start (or buildout--output-start (point-min))))
    (kill-new (buffer-substring-no-properties start (point-max)))
    (message "buildout: copied %d lines" (count-lines start (point-max)))))

(defun buildout-next-section (&optional n)
  "Move to the start of the Nth next section of output."
  (interactive "p")
  (dotimes (_ (or n 1))
    (let ((pos (save-excursion
                 (forward-line 1)
                 (when (and buildout--output-start (< (point) buildout--output-start))
                   (goto-char buildout--output-start))
                 (and (re-search-forward buildout--section-regexp nil t) (line-beginning-position)))))
      (when pos (goto-char pos)))))

(defun buildout-previous-section (&optional n)
  "Move to the start of the Nth previous section of output."
  (interactive "p")
  (dotimes (_ (or n 1))
    (let ((pos (save-excursion
                 (beginning-of-line)
                 (unless (bobp) (backward-char))
                 (and (re-search-backward buildout--section-regexp buildout--output-start t)
                      (line-beginning-position)))))
      (when pos (goto-char pos)))))

;;;; Keys

;;;###autoload (autoload 'buildout-command-map "buildout" nil t 'keymap)
(defvar buildout-command-map
  (let ((map (make-sparse-keymap)))
    (define-key map "g" #'buildout-run)
    (define-key map "t" #'buildout-think)
    (define-key map "w" #'buildout-think-at-point)
    (define-key map "l" #'buildout-think-line)
    (define-key map "i" #'buildout-what-if)
    (define-key map "b" #'buildout-bonds)
    (define-key map "h" #'buildout-history)
    (define-key map "a" #'buildout-ta)
    (define-key map "f" #'buildout-fa)
    (define-key map "e" #'buildout-engine)
    (define-key map "E" #'buildout-engine-list)
    (define-key map "d" #'buildout-doctor)
    (define-key map "m" #'buildout-bench)
    (define-key map "r" #'buildout-rerun)
    (define-key map "L" #'buildout-log)
    (define-key map "s" #'buildout-stop)
    (define-key map "o" #'buildout-show)
    (define-key map "T" #'buildout-triage)
    (define-key map "P" #'buildout-erp)
    (define-key map "D" #'buildout-dcf)
    (define-key map "M" #'buildout-ml)
    (define-key map "R" #'buildout-reality)
    map)
  "Keymap of Buildout commands; bind it to a prefix such as C-c b.")
(fset 'buildout-command-map buildout-command-map)

(defvar buildout-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c b") 'buildout-command-map)
    map)
  "Keymap for `buildout-mode': C-c b runs `buildout-command-map'.")

;;;###autoload
(define-minor-mode buildout-mode
  "Global minor mode that puts `buildout-command-map' on C-c b."
  :global t
  :lighter " Bo"
  :keymap buildout-mode-map
  :group 'buildout)

(define-obsolete-function-alias 'global-buildout-mode #'buildout-mode "0.17")

(provide 'buildout)
;;; buildout.el ends here

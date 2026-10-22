;;; buildout-test.el --- ERT tests for buildout.el  -*- lexical-binding: t; -*-

;;; Commentary:

;; Run from the repository folder:
;;   emacs -Q --batch -L editors -l editors/buildout-test.el -f ert-run-tests-batch-and-exit
;;
;; The process tests use small /bin/sh stubs in place of the engine, so
;; they need no Python and no network.

;;; Code:

(require 'ert)
(require 'buildout)

(defmacro buildout-test--with-repo (var &rest body)
  "Bind VAR to a temporary folder laid out like the repository, run BODY, then delete it."
  (declare (indent 1))
  `(let ((,var (file-name-as-directory (make-temp-file "buildout-test" t))))
     (unwind-protect
         (progn
           (make-directory (expand-file-name "buildout" ,var))
           (make-directory (expand-file-name "sub" ,var))
           (write-region "" nil (expand-file-name "pyproject.toml" ,var))
           ,@body)
       (delete-directory ,var t))))

(defun buildout-test--stub (dir code)
  "Write a script in DIR that prints its arguments and exits with CODE; return its path."
  (let ((file (expand-file-name (format "stub%d.sh" code) dir)))
    (write-region (format "#!/bin/sh\necho \"args: $*\"\nexit %d\n" code) nil file)
    (set-file-modes file #o755)
    file))

(defun buildout-test--wait (proc)
  "Wait up to ten seconds for PROC to finish and its sentinel to run."
  (let ((deadline (+ (float-time) 10)))
    (while (and proc (not (process-get proc 'buildout-done)) (< (float-time) deadline))
      (accept-process-output nil 0.05))))

(defun buildout-test--output ()
  "Return the text of the results buffer."
  (with-current-buffer buildout-buffer-name
    (buffer-substring-no-properties (point-min) (point-max))))

(ert-deftest buildout-test-split ()
  (should (equal (buildout--split "think \"Is AI a bubble?\" --json") '("think" "Is AI a bubble?" "--json")))
  (should (equal (buildout--split "a 'b c' d\\ e") '("a" "b c" "d e")))
  (should (equal (buildout--split "   ") nil)))

(ert-deftest buildout-test-display ()
  (should (equal (buildout--display '("think" "Is AI a bubble?")) "think 'Is AI a bubble?'"))
  (should (equal (buildout--display '("bonds" "--y10" "4")) "bonds --y10 4")))

(ert-deftest buildout-test-ticker-and-number ()
  (should (equal (buildout--clean-ticker "$nvda,") "NVDA"))
  (should (equal (buildout--clean-ticker "BRK.B.") "BRK.B"))
  (should-not (buildout--clean-ticker "two words"))
  (should (equal (buildout--number "4.25%") "4.25"))
  (should (equal (buildout--number 4) "4"))
  (should-not (buildout--number "four")))

(ert-deftest buildout-test-find-root ()
  (buildout-test--with-repo dir
    (let ((buildout-root nil))
      (should (equal (buildout--find-root (expand-file-name "sub/" dir)) dir)))))

(ert-deftest buildout-test-run-ok ()
  (skip-unless (executable-find "sh"))
  (buildout-test--with-repo dir
    (let ((buildout-root dir)
          (buildout-python (buildout-test--stub dir 0))
          (buildout-select-window nil))
      (buildout-test--wait (buildout--run '("think" "Is AI a bubble?")))
      (let ((out (buildout-test--output)))
        (should (string-match-p "^buildout think 'Is AI a bubble\\?'$" out))
        (should (string-match-p "^args: -m buildout think Is AI a bubble\\?$" out))
        (should (string-match-p "^done in " out)))
      (should (equal (car buildout-run-log) '("think" "Is AI a bubble?")))
      (with-current-buffer buildout-buffer-name
        (should (derived-mode-p 'buildout-results-mode))
        (should buffer-read-only)))))

(ert-deftest buildout-test-run-fails ()
  (skip-unless (executable-find "sh"))
  (buildout-test--with-repo dir
    (let ((buildout-root dir)
          (buildout-python (buildout-test--stub dir 2))
          (buildout-select-window nil))
      (buildout-test--wait (buildout--run '("bench")))
      (let ((out (buildout-test--output)))
        (should (string-match-p "^failed: exit 2 after " out))
        (should (string-match-p "exited with status 2" out))))))

(ert-deftest buildout-test-missing-python-and-root ()
  (buildout-test--with-repo dir
    (let ((buildout-root dir)
          (buildout-python "no-such-python-for-buildout")
          (buildout-select-window nil))
      (should-not (buildout--run '("doctor")))
      (should (string-match-p "python executable not found" (buildout-test--output))))
    (let ((buildout-root (expand-file-name "sub" dir))
          (buildout-python (buildout-test--stub dir 0))
          (buildout-select-window nil))
      (should-not (buildout--run '("doctor")))
      (should (string-match-p "no buildout package under" (buildout-test--output))))))

(ert-deftest buildout-test-keys ()
  (should (eq (lookup-key buildout-command-map "t") #'buildout-think))
  (should (eq (lookup-key buildout-command-map "r") #'buildout-rerun))
  (should (eq (lookup-key buildout-results-mode-map "y") #'buildout-copy-output)))

(provide 'buildout-test)
;;; buildout-test.el ends here

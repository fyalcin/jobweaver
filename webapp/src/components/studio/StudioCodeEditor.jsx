import React, { useRef, useMemo, useImperativeHandle } from 'react';

/**
 * StudioCodeEditor
 * High-performance controlled code editor with memoized line numbers and smooth native typing.
 */
export const StudioCodeEditor = React.forwardRef(function StudioCodeEditor(
  {
    value = '',
    onChange,
    onCompile,
    onSave,
    placeholder = '',
    className = '',
  },
  ref
) {
  const internalTextareaRef = useRef(null);
  const lineNumbersRef = useRef(null);

  // Expose textarea DOM element to parent if ref is provided
  useImperativeHandle(ref, () => internalTextareaRef.current);

  const handleChange = (e) => {
    if (onChange) {
      onChange(e.target.value);
    }
  };

  const handleScroll = () => {
    if (internalTextareaRef.current && lineNumbersRef.current) {
      lineNumbersRef.current.scrollTop = internalTextareaRef.current.scrollTop;
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const start = e.target.selectionStart;
      const end = e.target.selectionEnd;
      const cur = value || '';
      const nextVal = cur.substring(0, start) + '  ' + cur.substring(end);
      if (onChange) {
        onChange(nextVal);
      }
      setTimeout(() => {
        if (internalTextareaRef.current) {
          internalTextareaRef.current.selectionStart = internalTextareaRef.current.selectionEnd = start + 2;
        }
      }, 0);
    } else if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      if (onSave) {
        onSave();
      } else if (onCompile) {
        onCompile();
      }
    } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      if (onCompile) {
        onCompile();
      }
    }
  };

  // Only re-create line number elements when line count (\n) changes, NOT on every character edit!
  const linesCount = useMemo(() => (value || '').split('\n').length, [value]);
  const lineNumbers = useMemo(
    () => Array.from({ length: Math.max(linesCount, 1) }, (_, i) => i + 1),
    [linesCount]
  );

  return (
    <div className={`studio-editor-wrapper ${className}`}>
      <div className="studio-line-numbers" ref={lineNumbersRef} aria-hidden="true">
        {lineNumbers.map((num) => (
          <div key={num}>{num}</div>
        ))}
      </div>
      <textarea
        ref={internalTextareaRef}
        className="studio-textarea"
        value={value}
        onChange={handleChange}
        onScroll={handleScroll}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        spellCheck="false"
      />
    </div>
  );
});
